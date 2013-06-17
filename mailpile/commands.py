#!/usr/bin/python
import os
import os.path
import traceback

import mailpile.util
from mailpile.mailutils import Email, NotEditableError, NoFromAddressError, PrepareMail, SendMail
from mailpile.search import MailIndex, PostingList, GlobalPostingList
from mailpile.util import *

try:
  from GnuPGInterface import GnuPG
except ImportError:
  GnuPG = None


COMMANDS = {
  '0':  ('setup',    '',              'Perform initial setup',              60),
  'A:': ('add=',     'path/to/mbox',  'Add a mailbox',                      61),
  'a:': ('attach=',  'msg path/to/f', 'Attach a file to a message',         91),
  'c:': ('compose=', '[msg]',         '(Continue) Composing an e-mail',     90),
  'd:': ('delete=',  'msg',           'Delete a message from the index',    88),
  'e:': ('extract=', 'att msg [>fn]', 'Extract attachment(s) to file(s)',   86),
  'F:': ('filter=',  'options',       'Add/edit/delete auto-tagging rules', 56),
  'h':  ('help',     '',              'Print help on how to use mailpile',   0),
  'L':  ('load',     '',              'Load the metadata index',            63),
  'm:': ('mail=',    'msg [email]',   'Mail/bounce a message (to someone)', 99),
  'f:': ('forward=', '[att] m1 ...',  'Forward messages (and attachments)', 93),
  'n':  ('next',     '',              'Display next page of results',       81),
  'o:': ('order=',   '[rev-]what',   ('Sort by: date, from, subject, '
                                      'random or index'),                   83),
  'O':  ('optimize', '',              'Optimize the keyword search index',  64),
  'p':  ('previous', '',              'Display previous page of results',   82),
  'P:': ('print=',   'var',           'Print a setting',                    52),
  'r:': ('reply=',   '[all] m1 ...',  'Reply(-all) to one or more messages',92),
  'R':  ('rescan',   '',              'Scan all mailboxes for new messages',63),
  'g:': ('gpgrecv',  'key-ID',        'Fetch a GPG key from keyservers',    65),
  's:': ('search=',  'terms ...',     'Search!',                            80),
  'S:': ('set=',     'var=value',     'Change a setting',                   50),
  't:': ('tag=',     '[+|-]tag msg',  'Tag or untag search results',        84),
  'T:': ('addtag=',  'tag',           'Create a new tag',                   55),
  'U:': ('unset=',   'var',           'Reset a setting to the default',     51),
  'u':  ('update',   '',              'Force statistics update',            69),
  'v:': ('view=',    '[raw] m1 ...',  'View one or more messages',          85),
  'W':  ('www',      '',              'Just run the web server',            56),
}
def Choose_Messages(session, idx, words):
  msg_ids = set()
  all_words = []
  for word in words:
    all_words.extend(word.split(','))
  for what in all_words:
    if what.lower() == 'these':
      b, c = session.displayed
      msg_ids |= set(session.results[b:b+c])
    elif what.lower() == 'all':
      msg_ids |= set(session.results)
    elif what.startswith('='):
      try:
        msg_id = int(what[1:], 36)
        if msg_id >= 0 and msg_id < len(idx.INDEX):
          msg_ids.add(msg_id)
        else:
          session.ui.warning('ID out of bounds: %s' % (what[1:], ))
      except ValueError:
        session.ui.warning('What message is %s?' % (what, ))
    elif '-' in what:
      try:
        b, e = what.split('-')
        msg_ids |= set(session.results[int(b)-1:int(e)])
      except:
        session.ui.warning('What message is %s?' % (what, ))
    else:
      try:
        msg_ids.add(session.results[int(what)-1])
      except:
        session.ui.warning('What message is %s?' % (what, ))
  return msg_ids

def Action_Load(session, config, reset=False, wait=True, quiet=False):
  if not reset and config.index:
    return config.index
  def do_load():
    if reset:
      config.index = None
      if session:
        session.results = []
        session.searched = []
        session.displayed = (0, 0)
    idx = config.get_index(session)
    idx.update_tag_stats(session, config)
    if session:
      session.ui.reset_marks(quiet=quiet)
    return idx
  if wait:
    return config.slow_worker.do(session, 'Load', do_load)
  else:
    config.slow_worker.add_task(session, 'Load', do_load)
    return None

def Action_Tag(session, opt, arg, save=True):
  idx = Action_Load(session, session.config)
  try:
    words = arg.split()
    ops = []
    while words and words[0][0] in ('-', '+'):
      ops.append(words.pop(0))
    msg_ids = Choose_Messages(session, idx, words)
    for op in ops:
      tag_id = session.config.get_tag_id(op[1:])
      if op[0] == '-':
        idx.remove_tag(session, tag_id, msg_idxs=msg_ids, conversation=True)
      else:
        idx.add_tag(session, tag_id, msg_idxs=msg_ids, conversation=True)

    session.ui.reset_marks()

    if save:
      # Background save makes things feel fast!
      def background():
        idx.update_tag_stats(session, session.config)
        idx.save_changes()
      session.config.slow_worker.add_task(None, 'Save index', background)
    else:
      idx.update_tag_stats(session, session.config)

    return True

  except (TypeError, ValueError, IndexError):
    session.ui.reset_marks()
    session.ui.error('That made no sense: %s %s' % (opt, arg))
    return False

def Action_Filter_Add(session, config, flags, args):
  if args and args[0][0] == '=':
    tag_id = args.pop(0)[1:]
  else:
    tag_id = config.nid('filter')

  if 'read' in flags:
    terms = ['@read']
  elif 'new' in flags:
    terms = ['*']
  else:
    terms = session.searched

  if not terms or (len(args) < 1):
    raise UsageError('Need flags and search terms or a hook')

  tags, tids = [], []
  while args and args[0][0] in ('-', '+'):
    tag = args.pop(0)
    tags.append(tag)
    tids.append(tag[0]+config.get_tag_id(tag[1:]))

  if not args:
    args = ['Filter for %s' % ' '.join(tags)]

  if 'notag' not in flags and 'new' not in flags and 'read' not in flags:
    for tag in tags:
      if not Action_Tag(session, 'filter/tag', '%s all' % tag, save=False):
        raise UsageError()

  if (config.parse_set(session, ('filter:%s=%s'
                                 ) % (tag_id, ' '.join(args)))
  and config.parse_set(session, ('filter_tags:%s=%s'
                                 ) % (tag_id, ' '.join(tids)))
  and config.parse_set(session, ('filter_terms:%s=%s'
                                 ) % (tag_id, ' '.join(terms)))):
    session.ui.reset_marks()
    def save_filter():
      config.save()
      if config.index: config.index.save_changes()
    config.slow_worker.add_task(None, 'Save filter', save_filter)
  else:
    raise Exception('That failed, not sure why?!')

def Action_Filter_Delete(session, config, flags, args):
  if len(args) < 1 or args[0] not in config.get('filter', {}):
    raise UsageError('Delete what?')

  fid = args[0]
  if (config.parse_unset(session, 'filter:%s' % fid)
  and config.parse_unset(session, 'filter_tags:%s' % fid)
  and config.parse_unset(session, 'filter_terms:%s' % fid)):
    config.save()
  else:
    raise Exception('That failed, not sure why?!')

def Action_Filter_Move(session, config, flags, args):
  raise Exception('Unimplemented')

def Action_Filter(session, opt, arg):
  config = session.config
  args = arg.split()
  flags = []
  while args and args[0] in ('add', 'set', 'delete', 'move', 'list',
                             'new', 'read', 'notag'):
    flags.append(args.pop(0))
  try:
    if 'delete' in flags:
      return Action_Filter_Delete(session, config, flags, args)
    elif 'move' in flags:
      return Action_Filter_Move(session, config, flags, args)
    elif 'list' in flags:
      return session.ui.print_filters(config)
    else:
      return Action_Filter_Add(session, config, flags, args)
  except UsageError:
    pass
  except Exception, e:
    session.error(e)
    return
  session.ui.say(
    'Usage: filter [new|read] [notag] [=ID] <[+|-]tags ...> [description]\n'
    '       filter delete <id>\n'
    '       filter move <id> <pos>\n'
    '       filter list')

def Action_UpdateStats(session, config):
  idx = config.index
  tags = config.get("tag", {})
  idx.update_tag_stats(session, config, tags.keys())
  session.ui.say("Statistics updated.")

def Action_Rescan(session, config):
  if 'rescan' in config.RUNNING: return
  config.RUNNING['rescan'] = True
  idx = config.index
  count = 0
  rv = True
  try:
    pre_command = config.get('rescan_command', None)
    if pre_command:
      session.ui.mark('Running: %s' % pre_command)
      subprocess.check_call(pre_command, shell=True)
    count = 1
    for fid, fpath in config.get_mailboxes():
      if mailpile.util.QUITTING: break
      count += idx.scan_mailbox(session, fid, fpath, config.open_mailbox)
      config.clear_mbox_cache()
      session.ui.mark('\n')
    count -= 1
    if count:
      if not mailpile.util.QUITTING:
        GlobalPostingList.Optimize(session, idx, quick=True)
    else:
      session.ui.mark('Nothing changed')
  except (KeyboardInterrupt, subprocess.CalledProcessError), e:
    session.ui.mark('Aborted: %s' % e)
    if config.get('debug'):
      session.ui.say(traceback.format_exc())
    rv = False
  finally:
    if count:
      session.ui.mark('\n')
      if count < 500:
        idx.save_changes(session)
      else:
        idx.save(session)
  idx.update_tag_stats(session, config)
  session.ui.reset_marks()
  del config.RUNNING['rescan']
  return rv

def Action_Optimize(session, config, arg):
  try:
    idx = Action_Load(session, config)
    idx.save(session)
    GlobalPostingList.Optimize(session, idx, force=(arg == 'harder'))
    session.ui.reset_marks()
  except KeyboardInterrupt:
    session.ui.mark('Aborted')
    session.ui.reset_marks()
  return True

def Action_Attach(session, config, args):
  idx = Action_Load(session, config)
  session.ui.clear()

  files = []
  while os.path.exists(args[-1]):
    files.append(args.pop(-1))
  if not files:
    session.ui.error('No files found')
    return False

  emails = [Email(idx, i) for i in Choose_Messages(session, idx, args)]
  if not emails:
    session.ui.error('No messages selected')
    return False

  session.ui.say('Attaching %s to...' % ', '.join(files))
  for email in emails:
    subject = email.get_msg_info(MailIndex.MSG_SUBJECT)
    try:
      email.add_attachments(files)
      session.ui.say(' - %s' % subject)
    except NotEditableError:
      session.ui.error('Read-only message: %s' % subject)
    except:
      session.ui.error('Error attaching to %s' % subject)
      session.ui.say(traceback.format_exc())

  session.ui.reset_marks()
  return True

def Action_Compose(session, config, args):
  idx = Action_Load(session, config)
  if args:
    emails = [Email(idx, i) for i in Choose_Messages(session, idx, args)]
  else:
    local_id, lmbox = config.open_local_mailbox(session)
    emails = [Email.Create(idx, local_id, lmbox)]
    Action(session,
           'tag', '+Drafts =%s' % emails[0].get_msg_info(idx.MSG_IDX))
  if session.interactive:
    session.ui.clear()
    session.ui.reset_marks()
    session.ui.edit_messages(emails)
  else:
    session.ui.say('%d message(s) created as drafts' % len(emails))
  session.ui.reset_marks()
  return True

def Action_Reply(session, config, args):
  if args and args[0].lower() == 'all':
    reply_all = args.pop(0) or True
  else:
    reply_all = False

  idx = Action_Load(session, config)
  refs = [Email(idx, i) for i in Choose_Messages(session, idx, args)]
  if refs:
    trees = [m.evaluate_pgp(m.get_message_tree(), decrypt=True) for m in refs]
    ref_ids = [t['headers_lc'].get('message-id') for t in trees]
    ref_subjs = [t['headers_lc'].get('subject') for t in trees]
    msg_to = [t['headers_lc'].get('reply-to',
                                  t['headers_lc']['from']) for t in trees]
    msg_cc = []
    if reply_all:
      msg_cc += [t['headers_lc'].get('to', '') for t in trees]
      msg_cc += [t['headers_lc'].get('cc', '') for t in trees]
    msg_bodies = []
    for t in trees:
       # FIXME: Templates/settings for how we quote replies?
       text = (('%s wrote:\n' % t['headers_lc']['from']) +
               ''.join([p['data'] for p in t['text_parts']
                        if p['type'] in ('text', 'quote',
                                         'pgpsignedtext',
                                         'pgpsecuretext',
                                         'pgpverifiedtext')]))
       msg_bodies.append(text.replace('\n', '\n> '))

    local_id, lmbox = config.open_local_mailbox(session)
    try:
      email = Email.Create(idx, local_id, lmbox,
                           msg_text='\n\n'.join(msg_bodies),
                           msg_subject=('Re: %s' % ref_subjs[-1]),
                           msg_to=msg_to,
                           msg_cc=[r for r in msg_cc if r],
                           msg_references=[i for i in ref_ids if i])
      Action(session,
             'tag', '+Drafts =%s' % email.get_msg_info(idx.MSG_IDX))
    except NoFromAddressError:
      session.ui.warning('You must configure a From address first.')
      session.ui.reset_marks()
      return False

    if session.interactive:
      session.ui.clear()
      session.ui.reset_marks()
      session.ui.edit_messages([email])
    else:
      session.ui.say('Message created as draft')
      session.ui.reset_marks()
      return True
  else:
    session.ui.warning('No message found')
    session.ui.reset_marks()
    return False

def Action_Forward(session, config, args):
  if args and args[0].lower().startswith('att'):
    with_atts = args.pop(0) or True
  else:
    with_atts = False

  idx = Action_Load(session, config)
  refs = [Email(idx, i) for i in Choose_Messages(session, idx, args)]
  if refs:
    trees = [m.evaluate_pgp(m.get_message_tree(), decrypt=True) for m in refs]
    ref_subjs = [t['headers_lc']['subject'] for t in trees]
    msg_bodies = []
    msg_atts = []
    for t in trees:
       # FIXME: Templates/settings for how we quote forwards?
       text = '-------- Original Message --------\n'
       for h in ('Date', 'Subject', 'From', 'To'):
         v = t['headers_lc'].get(h.lower(), None)
         if v:
           text += '%s: %s\n' % (h, v)
       text += '\n'
       text += ''.join([p['data'] for p in t['text_parts']
                       if p['type'] in ('text', 'quote',
                                        'pgpsignedtext',
                                         'pgpsecuretext',
                                        'pgpverifiedtext')])
       msg_bodies.append(text)
       if with_atts:
         for att in t['attachments']:
           if att['mimetype'] not in ('application/pgp-signature', ):
             msg_atts.append(att['part'])

    local_id, lmbox = config.open_local_mailbox(session)
    email = Email.Create(idx, local_id, lmbox,
                         msg_text='\n\n'.join(msg_bodies),
                         msg_subject=('Fwd: %s' % ref_subjs[-1]))
    if msg_atts:
      msg = email.get_msg()
      for att in msg_atts:
        msg.attach(att)
      email.update_from_msg(msg)

    Action(session,
           'tag', '+Drafts =%s' % email.get_msg_info(idx.MSG_IDX))

    if session.interactive:
      session.ui.clear()
      session.ui.reset_marks()
      session.ui.edit_messages([email])
    else:
      session.ui.say('Message created as draft')
      session.ui.reset_marks()
      return True
  else:
    session.ui.warning('No message found')
    session.ui.reset_marks()
    return False

def Action_Mail(session, config, args):
  bounce_to = []
  while args and '@' in args[-1]:
    bounce_to.append(args.pop(-1))

  idx = Action_Load(session, config)
  session.ui.clear()
  session.ui.reset_marks()

  # Process one at a time so we don't eat too much memory
  for email in [Email(idx, i) for i in Choose_Messages(session, idx, args)]:
    try:
      SendMail(session, [PrepareMail(email, rcpts=(bounce_to or None))])
      msg_idx = emails[0].get_msg_info(idx.MSG_IDX)
      Action(session, 'tag', '-Drafts +Sent =%s' % msg_idx)
    except:
      session.ui.error('Failed to send %s' % email)
      print traceback.format_exc()

  session.ui.reset_marks()
  return True

def Action_Setup(session):
  # Create local mailboxes
  session.config.open_local_mailbox(session)

  # Create standard tags and filters
  tags = session.config.get('tag', {}).values()
  for t in ('New', 'Inbox', 'Spam', 'Drafts', 'Sent', 'Trash'):
    if t not in tags:
      Action(session, 'addtag', t)
  if 'New' not in tags:
    Action(session, 'filter', 'new +Inbox +New New Mail filter')
    Action(session, 'filter', 'read -New Read Mail filter')

  return True

def Action(session, opt, arg):
  config = session.config
  session.ui.reset_marks(quiet=True)
  num_results = config.get('num_results', None)

  if not opt or opt in ('h', 'help'):
    session.ui.print_help(COMMANDS, tags=config.get('tag', {}),
                                    index=config.get_index(session))

  elif opt in ('0', 'setup'):
    Action_Setup(session)

  elif opt in ('A', 'add'):
    if arg in config.get('mailbox', {}).values():
      session.ui.warning('Already in the pile: %s' % arg)
    else:
      if os.path.exists(arg):
        arg = os.path.abspath(arg)
        if config.parse_set(session,
                            'mailbox:%s=%s' % (config.nid('mailbox'), arg)):
          config.slow_worker.add_task(None, 'Save config', lambda: config.save())
      else:
        session.error('No such file/directory: %s' % arg)

  elif opt in ('F', 'filter'):
    Action_Filter(session, opt, arg)

  elif opt in ('L', 'load'):
    Action_Load(session, config, reset=True)

  elif opt in ('O', 'optimize'):
    config.slow_worker.do(session, 'Optimize',
                          lambda: Action_Optimize(session, config, arg))

  elif opt in ('P', 'print'):
    session.ui.print_key(arg.strip().lower(), config)

  elif opt in ('R', 'rescan'):
    Action_Load(session, config)
    config.slow_worker.do(session, 'Rescan',
                          lambda: Action_Rescan(session, config))

  elif opt in ('S', 'set'):
    if config.parse_set(session, arg):
      config.slow_worker.add_task(None, 'Save config', lambda: config.save())

  elif opt in ('T', 'addtag'):
    if (arg
    and ' ' not in arg
    and arg.lower() not in [v.lower() for v in config.get('tag', {}).values()]):
      if config.parse_set(session,
                          'tag:%s=%s' % (config.nid('tag'), arg)):
        config.slow_worker.add_task(None, 'Save config', lambda: config.save())
    else:
      session.error('Invalid tag: %s' % arg)

  elif opt in ('U', 'unset'):
    if config.parse_unset(session, arg):
      config.slow_worker.add_task(None, 'Save config', lambda: config.save())

  elif opt in ('W', 'www'):
    config.prepare_workers(session, daemons=True)
    while not mailpile.util.QUITTING: time.sleep(1)

  elif opt in ('a', 'attach'):
    Action_Attach(session, config, arg.split())

  elif opt in ('c', 'compose'):
    Action_Compose(session, config, arg.split())

  elif opt in ('e', 'extract'):
    args = arg.split()
    idx = Action_Load(session, config)
    cid = args.pop(0)
    if len(args) > 0 and args[-1].startswith('>'):
      name_fmt = args.pop(-1)[1:]
    else:
      name_fmt = None
    emails = [Email(idx, i) for i in Choose_Messages(session, idx, args)]
    for email in emails:
      email.extract_attachment(session, cid, name_fmt=name_fmt)
    session.ui.reset_marks()

  elif opt in ('f', 'forward'):
    Action_Forward(session, config, arg.split())

  elif opt in ('g', 'gpgrecv'):
    try:
      session.ui.mark('Invoking GPG to fetch key %s' % arg)
      keyserver = config.get('gpg_keyserver', 'pool.sks-keyservers.net')
      gpg = GnuPG().run(['--utf8-strings',
                         '--keyserver', keyserver,
                         '--recv-key', arg], create_fhs=['stderr'])
      session.ui.say(gpg.handles['stderr'].read().decode('utf-8'))
      gpg.handles['stderr'].close()
      gpg.wait()
    except IOError:
      pass
    session.ui.reset_marks()

  elif opt in ('m', 'mail'):
    Action_Mail(session, config, arg.split())

  elif opt in ('n', 'next'):
    idx = Action_Load(session, config)
    session.ui.reset_marks()
    pos, count = session.displayed
    session.displayed = session.ui.display_results(idx, session.results,
                                                   session.searched,
                                                   start=pos+count,
                                                   num=num_results)
    session.ui.reset_marks()

  elif opt in ('o', 'order'):
    idx = Action_Load(session, config)
    session.order = arg or None
    idx.sort_results(session, session.results,
                     how=session.order)
    session.displayed = session.ui.display_results(idx, session.results,
                                                   session.searched,
                                                   num=num_results)
    session.ui.reset_marks()

  elif opt in ('p', 'previous'):
    idx = Action_Load(session, config)
    pos, count = session.displayed
    session.displayed = session.ui.display_results(idx, session.results,
                                                   session.searched,
                                                   end=pos,
                                                   num=num_results)
    session.ui.reset_marks()

  elif opt in ('r', 'reply'):
    Action_Reply(session, config, arg.split())

  elif (opt in ('s', 'search')
        or opt.lower() in [t.lower() for t in config.get('tag', {}).values()]):
    idx = Action_Load(session, config)

    # FIXME: This is all rather dumb.  Make it smarter!

    session.searched = []
    if opt not in ('s', 'search'):
      tid = config.get_tag_id(opt)
      session.searched = ['tag:%s' % tid[0]]

    if arg.startswith('@'):
      try:
        if ' ' in arg:
          args = arg[1:].split(' ')
          start = args.pop(0)
        else:
          start, args = arg[1:], []
        start = int(start)-1
        arg = ' '.join(args)
      except ValueError:
        raise UsageError('Weird starting point')
    else:
      start = 0

    if ':' in arg or '-' in arg or '+' in arg:
      session.searched.extend(arg.lower().split())
    else:
      session.searched.extend(re.findall(WORD_REGEXP, arg.lower()))

    session.results = list(idx.search(session, session.searched))
    idx.sort_results(session, session.results, how=session.order)
    session.displayed = session.ui.display_results(idx, session.results,
                                                   session.searched,
                                                   start=start,
                                                   num=num_results)
    session.ui.reset_marks()

  elif opt in ('t', 'tag'):
    Action_Tag(session, opt, arg)

  elif opt in ('u', 'updatestats'):
    Action_UpdateStats(session, config)

  elif opt in ('v', 'view'):
    args = arg.split()
    if args and args[0].lower() == 'raw':
      raw = args.pop(0)
    else:
      raw = False
    idx = Action_Load(session, config)
    emails = [Email(idx, i) for i in Choose_Messages(session, idx, args)]
    if emails:
      idx.apply_filters(session, '@read', msg_idxs=[e.msg_idx for e in emails])
      session.ui.clear()
      session.ui.display_messages(emails, raw=raw)
    session.ui.reset_marks()

  else:
    raise UsageError('Unknown command: %s' % opt)
