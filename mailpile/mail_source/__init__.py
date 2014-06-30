import os
import random
import re
import thread
import threading
import traceback
import time
from gettext import gettext as _

import mailpile.util
from mailpile.util import *
from mailpile.eventlog import Event
from mailpile.mailboxes import *
from mailpile.mailutils import FormatMbxId


__all__ = ['mbox', 'maildir', 'imap']


class BaseMailSource(threading.Thread):
    """
    MailSources take care of managing a group of mailboxes, synchronizing
    the source with Mailpile's local metadata and/or caches.
    """
    DEFAULT_JITTER = 15         # Fudge factor to tame thundering herds
    SAVE_STATE_INTERVAL = 3600  # How frequently we pickle our state
    INTERNAL_ERROR_SLEEP = 900  # Pause time on error, in seconds
    RESCAN_BATCH_SIZE = 2500    # Index at most this many new e-mails at once
    MAX_PATHS = 50000           # Abort if asked to scan too many directories

    # This is a helper for the events.
    __classname__ = 'mailpile.mail_source.BaseMailSource'

    def __init__(self, session, my_config):
        threading.Thread.__init__(self)
        self._lock = threading.Lock()
        self.my_config = my_config
        self.session = session
        self.alive = None
        self.event = None
        self.jitter = self.DEFAULT_JITTER
        self._state = 'Idle'
        self._sleeping = None
        self._interrupt = None
        self._rescanning = False
        self._rescan_waiters = []
        self._last_rescan_count = 0
        self._last_saved = time.time()  # Saving right away would be silly

        # Make locked versions of a few functions
        self._load_state = self._locked(self._unlocked_load_state)
        self.open = self._locked(self._unlocked_open)
        self.sync_mail = self._locked(self._unlocked_sync_mail)
        self.rescan_mailbox = self._locked(self._unlocked_rescan_mailbox)
        self.take_over_mailbox = self._locked(self._unlocked_take_over_mailbox)
        self.discover_mailboxes = self._locked(
            self._unlocked_discover_mailboxes)

    def __str__(self):
        rv = ': '.join([threading.Thread.__str__(self), self._state])
        if self._sleeping > 0:
            rv += '(%s)' % self._sleeping
        return rv

    def _locked(self, func):
        def locked_func(*args, **kwargs):
            try:
                self._lock.acquire()
                ostate, self._state = self._state, func.__name__
                return func(*args, **kwargs)
            except:
                traceback.print_exc()
                raise
            finally:
                self._state = ostate
                try:
                    self._lock.release()
                except thread.error:
                    pass
        return locked_func

    def _pfn(self):
        return 'mail-source.%s' % self.my_config._key

    def _unlocked_load_state(self):
        config, my_config = self.session.config, self.my_config
        events = list(config.event_log.incomplete(source=self,
                                                  data_id=my_config._key))
        if events:
            self.event = events[0]
        else:
            self.event = config.event_log.log(source=self,
                                              flags=Event.RUNNING,
                                              message=_('Starting up'),
                                              data={'id': my_config._key})

    def _save_state(self):
        self.session.config.event_log.log_event(self.event)

    def _log_status(self, message):
        self.event.message = message
        self.session.config.event_log.log_event(self.event)
        if 'sources' in self.session.config.sys.debug:
            self.session.ui.debug('%s: %s' % (self, message))

    def _unlocked_open(self):
        """Open mailboxes or connect to the remote mail source."""
        raise NotImplemented('Please override _open in %s' % self)

    def _has_mailbox_changed(self, mbx, state):
        """For the default sync_mail routine, report if mailbox changed."""
        raise NotImplemented('Please override _open in %s' % self)

    def _mark_mailbox_rescanned(self, mbx, state):
        """For the default sync_mail routine, note mailbox was rescanned."""
        raise NotImplemented('Please override _open in %s' % self)

    def _path(self, mbx):
        if mbx.path.startswith('@'):
            return self.session.config.sys.mailbox[mbx.path[1:]]
        else:
            return mbx.path

    def _unlocked_sync_mail(self):
        """Iterates through all the mailboxes and scans if necessary."""
        def unsorted(l):
            l.sort(key=lambda k: random.randint(0, 500))
            return l
        config = self.session.config
        self._last_rescan_count = rescanned = errors = 0
        self._interrupt = None
        batch = self.RESCAN_BATCH_SIZE
        errors = rescanned = 0
        if self.session.config.sys.debug:
            batch //= 10
        for mbx in unsorted(self.my_config.mailbox.values()):
            if mailpile.util.QUITTING or self._interrupt:
                self._log_status(_('Interrupted: %s'
                                   ) % (self._interrupt or _('Quitting')))
                self._interrupt = None
                break
            try:
                state = {}
                # Generally speaking, we only rescan if a mailbox looks like
                # it has changed. However, 1/20th of the time we take a look
                # anyway just in case looks are deceiving.
                if batch > 0 and (self._has_mailbox_changed(mbx, state) or
                                  random.randint(0, 20) == 10):

                    count = self._unlocked_rescan_mailbox(mbx._key,
                                                          stop_after=batch)
                    if count >= 0:
                        batch -= count
                        if (count and batch > 0 and
                                not self._interrupt and
                                not mailpile.util.QUITTING):
                            self._mark_mailbox_rescanned(mbx, state)
                            rescanned += 1
                    else:
                        errors += 1
            except (NoSuchMailboxError, IOError, OSError):
                errors += 1
            except:
                self._log_status(_('Internal error'))
                raise

        if batch > 0 and not errors:
            self._log_status(_('Checking for new mailboxes'))
            self._unlocked_discover_mailboxes(self.my_config.discovery.paths)

        if errors:
            self._log_status(_('Rescanned %d mailboxes, failed to rescan %d'
                               ) % (rescanned, errors))
        else:
            self._log_status(_('Rescanned %d mailboxes') % rescanned)
        self._last_rescan_count = rescanned
        return rescanned

    def _jitter(self, seconds):
        return seconds + random.randint(0, self.jitter)

    def _sleep(self, seconds):
        if self.session.config.sys.debug:
            seconds //= 10
        if self._sleeping != 0:
            self._sleeping = seconds
            while (self.alive and self._sleeping > 0 and
                    not mailpile.util.QUITTING):
                time.sleep(min(1, self._sleeping))
                self._sleeping -= 1
        self._sleeping = None
        return (self.alive and not mailpile.util.QUITTING)

    def _existing_mailboxes(self):
        return set(self.session.config.sys.mailbox +
                   [mbx.local for mbx in self.my_config.mailbox.values()
                    if mbx.local])

    def _unlocked_discover_mailboxes(self, paths):
        config = self.session.config
        existing = self._existing_mailboxes()
        adding = []
        paths = paths[:]
        while paths:
            raw_fn = paths.pop(0)
            fn = os.path.abspath(os.path.normpath(os.path.expanduser(raw_fn)))
            if raw_fn in existing or fn in existing or not os.path.exists(fn):
                continue
            if self.is_mailbox(fn):
                adding.append(fn)
            if os.path.isdir(fn):
                try:
                    for f in [f for f in os.listdir(fn)
                              if f not in ('.', '..')]:
                        paths.append(os.path.join(fn, f))
                        if len(paths) > self.MAX_PATHS:
                            return False
                except OSError:
                    pass

        new = {}
        for path in adding:
            new[config.sys.mailbox.append(path)] = path
        for mailbox_idx in new.keys():
            mbx = self._unlocked_take_over_mailbox(mailbox_idx)
            if mbx.policy != 'unknown':
                del new[mailbox_idx]
        if new:
            self.event.data['have_unknown'] = True

        return True

    def _unlocked_take_over_mailbox(self, mailbox_idx):
        config = self.session.config
        disco_cfg = self.my_config.discovery  # Stayin' alive! Stayin' alive!
        mailbox_idx = FormatMbxId(mailbox_idx)
        self.my_config.mailbox[mailbox_idx] = {
            'path': '@%s' % mailbox_idx,
            'policy': disco_cfg.policy,
            'process_new': disco_cfg.process_new,
        }
        mbx = self.my_config.mailbox[mailbox_idx]
        mbx.apply_tags.extend(disco_cfg.apply_tags)
        if disco_cfg.create_tag:
            tag_name_or_id = self._create_tag_name(self._path(mbx))
            mbx['primary_tag'] = tag_name_or_id
            if disco_cfg.policy != 'unknown':
                try:
                    mbx['primary_tag'] = self._create_tag(tag_name_or_id,
                                                          unique=True)
                except ValueError:
                    pass  # FIXME: This suxors
        if disco_cfg.local_copy:
            path, wervd = config.create_local_mailstore(self.session)
            mbx.local = path
        return mbx

    BORING_FOLDER_RE = re.compile('(?i)^(home|mail|data|user\S*|[^a-z]+)$')

    def _path_to_tagname(self, path):  # -> tag name
        """This converts a path to a tag name."""
        path = path.replace('/.', '/')
        parts = ('/' in path) and path.split('/') or path.split('\\')
        parts = [p for p in parts if not re.match(self.BORING_FOLDER_RE, p)]
        tagname = parts.pop(-1).split('.')[0]
        if self.session.config.get_tags(tagname):
            tagname = '%s/%s' % (parts[-1], tagname)
        return tagname.replace('-', ' ').replace('_', ' ')

    def _unique_tag_name(self, tagname):  # -> unused tag name
        """This makes sure a tagname really is unused"""
        tagnameN, count = tagname, 2
        while self.session.config.get_tags(tagnameN):
            tagnameN = '%s (%s)' % (tagname, count)
            count += 1
        return tagnameN

    def _create_tag_name(self, path):  # -> unique tag name
        """Convert a path to a unique tag name."""
        return self._unique_tag_name(self._path_to_tagname(path))

    def _create_tag(self, tag_name_or_id, unique=False):  # -> tag ID
        tags = self.session.config.get_tags(tag_name_or_id)
        if tags and unique:
            raise ValueError('Tag name is not unique!')
        elif len(tags) == 1:
            tag_id = tags[0]._key
        elif len(tags) > 1:
            raise ValueError('Tag name matches multiple tags!')
        else:
            from mailpile.plugins.tags import AddTag
            AddTag(self.session, arg=[tag_name_or_id]).run(save=False)
            tags = self.session.config.get_tags(tag_name_or_id)
            tag_id = tags[0]._key
        return tag_id

    def interrupt_rescan(self, reason):
        self._interrupt = reason or _('Aborted')
        if self._rescanning:
            self.session.config.index.interrupt = reason

    def _process_new(self, msg, msg_ts, keywords, snippet):
        return ProcessNew(self.session, msg, msg_ts, keywords, snippet)

    def _unlocked_rescan_mailbox(self, mbx_key, stop_after=None):
        mbx_key = FormatMbxId(mbx_key)
        if self._rescanning:
            # We unlock below, so there is a chance someone will try to
            # rescan again while we're in a mailbox. If they do, fail.
            return -1
        try:
            self._rescanning = True
            ostate, self._state = self._state, 'Rescan(%s, %s)' % (mbx_key,
                                                                   stop_after)

            mbx = self.my_config.mailbox[mbx_key]
            path = self._path(mbx)
            if (path in ('/dev/null', '', None)
                    or mbx.policy in ('ignore', 'unknown')):
                return 0
            if mbx.local:
                # FIXME: Should copy any new messages to our local stash
                pass
            self._log_status(_('Rescanning: %s') % path)
            apply_tags = mbx.apply_tags[:]
            if mbx.primary_tag:
                apply_tags.append(mbx.primary_tag)
            locked = self._lock.locked()
            try:
                if locked:
                    # We need to unlock here, because the mailbox scanner
                    # may need to interact with us.
                    try:
                        self._lock.release()
                    except thread.error:
                        locked = False
                return self.session.config.index.scan_mailbox(
                    self.session, mbx_key, mbx.local or path,
                    self.session.config.open_mailbox,
                    process_new=(mbx.process_new and self._process_new or False),
                    apply_tags=(apply_tags or []),
                    stop_after=stop_after)
            finally:
                if locked:
                    self._lock.acquire()
        except ValueError:
            self.session.ui.debug(traceback.format_exc())
            return -1
        finally:
            self._state = ostate
            self._rescanning = False

    def open_mailbox(self, mbx_id, fn):
        # This allows mail sources to override the default mailbox
        # opening mechanism.  Returning false respectfully declines.
        return False

    def is_mailbox(self, fn):
        return False

    def run(self):
        self.alive = True
        self._load_state()
        self.event.flags = Event.RUNNING
        _original_session = self.session
        while self._sleep(self._jitter(self.my_config.interval)):
            if not self.session.config.index:
                continue
            waiters, self._rescan_waiters = self._rescan_waiters, []
            for b, e, s in waiters:
                try:
                    b.release()
                except thread.error:
                    pass
                if s:
                    self.session = s
            try:
                if 'traceback' in self.event.data:
                    del self.event.data['traceback']
                if self.open():
                    self.sync_mail()
                next_save_time = self._last_saved + self.SAVE_STATE_INTERVAL
                if self.alive and time.time() >= next_save_time:
                    self._save_state()
            except:
                self.event.data['traceback'] = traceback.format_exc()
                self.session.ui.debug(self.event.data['traceback'])
                self._log_status(_('Internal error!  Sleeping...'))
                self._sleep(self.INTERNAL_ERROR_SLEEP)
            finally:
                for b, e, s in waiters:
                    try:
                        e.release()
                    except thread.error:
                        pass
                self.session = _original_session
        self._save_state()
        self.event.flags = Event.COMPLETE
        self._log_status(_('Shut down'))

    def wake_up(self):
        self._sleeping = 0

    def rescan_now(self, session=None, started_callback=None):
        begin, end = threading.Lock(), threading.Lock()
        for l in (begin, end):
            l.acquire()
        try:
            self._rescan_waiters.append((begin, end, session))
            self.wake_up()
            while not begin.acquire(False):
                time.sleep(1)
                if mailpile.util.QUITTING:
                    return self._last_rescan_count
            if started_callback:
                started_callback()
            while not end.acquire(False):
                time.sleep(1)
                if mailpile.util.QUITTING:
                    return self._last_rescan_count
            return self._last_rescan_count
        except KeyboardInterrupt:
            self.interrupt_rescan(_('User aborted'))
            raise
        finally:
            for l in (begin, end):
                try:
                    l.release()
                except thread.error:
                    pass

    def quit(self, join='ignored'):
        self.interrupt_rescan(_('Shut down'))
        self.alive = False
        self.wake_up()


def ProcessNew(session, msg, msg_ts, keywords, snippet):
    if 'r' in msg.get('status', '').lower():
        return False
    keywords.update(['%s:in' % tag._key for tag in
                     session.config.get_tags(type='unread')])
    return True


def MailSource(session, my_config):
    # FIXME: check the plugin and instanciate the right kind of mail source
    #        for this config section.
    if my_config.protocol in ('mbox',):
        from mailpile.mail_source.mbox import MboxMailSource
        return MboxMailSource(session, my_config)
    elif my_config.protocol in ('maildir',):
        from mailpile.mail_source.maildir import MaildirMailSource
        return MaildirMailSource(session, my_config)
    elif my_config.protocol in ('imap', 'imap_ssl'):
        from mailpile.mail_source.imap import ImapMailSource
        return ImapMailSource(session, my_config)
    raise ValueError(_('Unknown mail source protocol: %s'
                       ) % my_config.protocol)
