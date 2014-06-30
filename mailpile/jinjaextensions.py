import copy
import datetime
import hashlib
import re
import urllib
import json
import shlex
from gettext import gettext as _
from jinja2 import nodes, UndefinedError, Markup
from jinja2.ext import Extension
from jinja2.utils import contextfunction, import_string
#from markdown import markdown

from mailpile.commands import Action
from mailpile.util import *
from mailpile.ui import HttpUserInteraction
from mailpile.urlmap import UrlMap
from mailpile.plugins import PluginManager


class MailpileCommand(Extension):
    """Run Mailpile Commands, """
    tags = set(['mpcmd'])

    def __init__(self, environment):
        Extension.__init__(self, environment)
        self.env = environment
        environment.globals['mailpile'] = self._command
        environment.globals['mailpile_render'] = self._command_render
        environment.globals['use_data_view'] = self._use_data_view
        environment.globals['regex_replace'] = self._regex_replace
        environment.filters['regex_replace'] = self._regex_replace
        environment.globals['friendly_bytes'] = self._friendly_bytes
        environment.filters['friendly_bytes'] = self._friendly_bytes
        environment.globals['friendly_number'] = self._friendly_number
        environment.filters['friendly_number'] = self._friendly_number
        environment.globals['show_avatar'] = self._show_avatar
        environment.filters['show_avatar'] = self._show_avatar
        environment.globals['navigation_on'] = self._navigation_on
        environment.filters['navigation_on'] = self._navigation_on
        environment.globals['has_label_tags'] = self._has_label_tags
        environment.filters['has_label_tags'] = self._has_label_tags
        environment.globals['show_message_signature'
                            ] = self._show_message_signature
        environment.filters['show_message_signature'
                            ] = self._show_message_signature
        environment.globals['show_message_encryption'
                            ] = self._show_message_encryption
        environment.filters['show_message_encryption'
                            ] = self._show_message_encryption
        environment.globals['contact_url'] = self._contact_url
        environment.filters['contact_url'] = self._contact_url
        environment.globals['contact_name'] = self._contact_name
        environment.filters['contact_name'] = self._contact_name
        environment.globals['fix_urls'] = self._fix_urls
        environment.filters['fix_urls'] = self._fix_urls

        # See utils.py for these functions:
        environment.globals['elapsed_datetime'] = elapsed_datetime
        environment.filters['elapsed_datetime'] = elapsed_datetime
        environment.globals['friendly_datetime'] = friendly_datetime
        environment.filters['friendly_datetime'] = friendly_datetime
        environment.globals['friendly_time'] = friendly_time
        environment.filters['friendly_time'] = friendly_time

        # These are helpers for injecting plugin elements
        environment.globals['get_ui_elements'] = self._get_ui_elements
        environment.globals['ui_elements_setup'] = self._ui_elements_setup
        environment.filters['add_state_query_string'] = self._add_state_query_string

        # This is a worse versin of urlencode, but without it we require
        # Jinja 2.7, which isn't apt-get installable.
        environment.globals['urlencode'] = self._urlencode
        environment.filters['urlencode'] = self._urlencode

        # Make a function-version of the safe command
        environment.globals['safe'] = self._safe
        environment.filters['json'] = self._json

        # Strip trailing blank lines from email
        environment.globals['nice_text'] = self._nice_text
        environment.filters['nice_text'] = self._nice_text

        # Strip Re: Fwd: from subject lines
        environment.globals['nice_subject'] = self._nice_subject
        environment.filters['nice_subject'] = self._nice_subject

        # Make unruly names a lil bit nicer
        environment.globals['nice_name'] = self._nice_name
        environment.filters['nice_name'] = self._nice_name

        # Makes a UI usable classification of attachment from mimetype
        environment.globals['attachment_type'] = self._attachment_type
        environment.filters['attachment_type'] = self._attachment_type

        # Loads theme settings JSON manifest
        environment.globals['theme_settings'] = self._theme_settings
        environment.filters['theme_settings'] = self._theme_settings

        # Separates Fingerprint in 4 char groups
        environment.globals['nice_fingerprint'] = self._nice_fingerprint
        environment.filters['nice_fingerprint'] = self._nice_fingerprint

        # Converts Filter +/- tags into arrays
        environment.globals['make_filter_groups'] = self._make_filter_groups
        environment.filters['make_filter_groups'] = self._make_filter_groups

        # Make Nice Summary of Recipients
        environment.globals['recipient_summary'] = self._recipient_summary
        environment.filters['recipient_summary'] = self._recipient_summary

    def _command(self, command, *args, **kwargs):
        rv = Action(self.env.session, command, args, data=kwargs).as_dict()
        if 'jinja' in self.env.session.config.sys.debug:
            sys.stderr.write('mailpile(%s, %s, %s) -> %s' % (
                command, args, kwargs, rv))
        return rv

    def _command_render(self, how, command, *args, **kwargs):
        old_ui, config = self.env.session.ui, self.env.session.config
        try:
            ui = self.env.session.ui = HttpUserInteraction(None, config,
                                                           log_parent=old_ui,
                                                           log_prefix='jinja/')
            ui.html_variables = copy.deepcopy(old_ui.html_variables)
            ui.render_mode = how
            ui.display_result(Action(self.env.session, command, args,
                                     data=kwargs))
            return ui.render_response(config)
        finally:
            self.env.session.ui = old_ui

    def _use_data_view(self, view_name, result):
        dv = UrlMap(self.env.session).map(None, 'GET', view_name, {}, {})[-1]
        return dv.view(result)

    def _get_ui_elements(self, ui_type, state, context=None):
        ctx = context or state.get('context_url', '')
        return copy.deepcopy(PluginManager().get_ui_elements(ui_type, ctx))

    def _add_state_query_string(self, url, state, elem=None):
        if not url:
            url = state.get('command_url', '')
        if '#' in url:
            url, frag = url.split('#', 1)
            frag = '#' + frag
        else:
            frag = ''
        if url:
            args = []
            query_args = state.get('query_args', {})
            for key in sorted(query_args.keys()):
                if key.startswith('_'):
                    continue
                values = query_args[key]
                if elem:
                    for rk, rv in elem.get('url_args_remove', []):
                        if rk == key:
                            values = [v for v in values if rv and (v != rv)]
                if elem:
                    for ak, av in elem.get('url_args_add', []):
                        if ak == key and av not in values:
                            values.append(av)
                args.extend([(key, v.encode("utf-8")) for v in values])
            return url + '?' + urllib.urlencode(args) + frag
        else:
            return url + frag

    def _ui_elements_setup(self, classfmt, elements):
        setups = []
        for elem in elements:
            if elem.get('javascript_setup'):
                setups.append('$("%s").each(function(){%s(this);});'
                              % (classfmt % elem, elem['javascript_setup']))
            if elem.get('javascript_events'):
                for event, call in elem.get('javascript_events').iteritems():
                    setups.append('$("%s").bind("%s", %s);' %
                        (classfmt % elem, event, call))
        return Markup("function(){%s}" % ''.join(setups))

    def _regex_replace(self, s, find, replace):
        """A non-optimal implementation of a regex filter"""
        return re.sub(find, replace, s)

    def _friendly_number(self, number, decimals=0):
        # See mailpile/util.py:friendly_number if this needs fixing
        return friendly_number(number, decimals=decimals, base=1000)

    def _friendly_bytes(self, number, decimals=0):
        # See mailpile/util.py:friendly_number if this needs fixing
        return friendly_number(number,
                               decimals=decimals, base=1024, suffix='B')

    def _show_avatar(self, contact):
        if "photo" in contact:
            photo = contact['photo']
        else:
            photo = '/static/img/avatar-default.png'
        return photo

    def _navigation_on(self, search_tag_ids, on_tid):
        if search_tag_ids:
            for tid in search_tag_ids:
                if tid == on_tid:
                    return "navigation-on"
                else:
                    return ""

    def _has_label_tags(self, tags, tag_tids):
        count = 0
        for tid in tag_tids:
            if tags[tid]["label"] and not tags[tid]["searched"]:
                count += 1
        return count

    _DEFAULT_SIGNATURE = [
            "crypto-color-gray",
            "icon-signature-none",
            _("Unknown"),
            _("There is something unknown or wrong with this signature")]
    _STATUS_SIGNATURE = {
        "none": [
            "crypto-color-gray",
            "icon-signature-none",
            _("Not Signed"),
            _("This message contains no signature, which means it could "
              "have come from anyone, not necessarily the real sender")],
        "error": [
            "crypto-color-red",
            "icon-signature-error",
            _("Error"),
            _("There was a weird error with this signature")],
        "mixed-error": [
            "crypto-color-red",
            "icon-signature-error",
            _("Mixed Error"),
            _("Parts of this message have a signature with a weird error")],
        "invalid": [
            "crypto-color-red",
            "icon-signature-invalid",
            _("Invalid"),
            _("The signature was invalid or bad")],
        "mixed-invalid": [
            "crypto-color-red",
            "icon-signature-invalid",
            _("Mixed Invalid"),
            _("Parts of this message has a signature that are invalid"
              " or bad")],
        "revoked": [
            "crypto-color-red",
            "icon-signature-revoked",
            _("Revoked"),
            _("Watch out, the signature was made with a key that has been"
              "revoked- this is not a good thing")],
        "mixed-revoked": [
            "crypto-color-red",
            "icon-signature-revoked",
            _("Mixed Revoked"),
            _("Watch out, parts of this message were signed from a key that "
              "has been revoked")],
        "expired": [
            "crypto-color-red",
            "icon-signature-expired",
            _("Expired"),
            _("The signature was made with an expired key")],
        "mixed-expired": [
            "crypto-color-red",
            "icon-signature-expired",
            _("Mixed Expired"),
            _("Parts of this message have a signature made with an "
              "expired key")],
        "unknown": [
            "crypto-color-orange",
            "icon-signature-unknown",
            _("Unknown"),
            _("The signature was made with an unknown key, so we can not "
              "verify it")],
        "mixed-unknown": [
            "crypto-color-orange",
            "icon-signature-unknown",
            _("Mixed Unknown"),
            _("Parts of this message have a signature made with an unknown "
              "key which we can not verify")],
        "unverified": [
            "crypto-color-blue",
            "icon-signature-unverified",
            _("Unverified"),
            _("The signature was good but it came from a key that is not "
              "verified yet")],
        "mixed-unverified": [
            "crypto-color-blue",
            "icon-signature-unverified",
            _("Mixed Unverified"),
            _("Parts of this message have an unverified signature")],
        "verified": [
            "crypto-color-green",
            "icon-signature-verified",
            _("Verified"),
            _("The signature was good and came from a verified key, w00t!")],
        "mixed-verified": [
            "crypto-color-blue",
            "icon-signature-verified",
            _("Mixed Verified"),
            _("Parts of the message have a verified signature, but other "
              "parts do not")]
    }

    @classmethod
    def _show_message_signature(self, status):
        # This avoids crashes when attributes are missing.
        try:
            if status.startswith('hack the planet'):
                pass
        except UndefinedError:
            status = ''

        color, icon, text, message = self._STATUS_SIGNATURE.get(status, self._DEFAULT_SIGNATURE)

        return {
            'color': color,
            'icon': icon,
            'text': text,
            'message': message
        }

    _DEFAULT_ENCRYPTION = [
        "crypto-color-gray",
        "icon-lock-open",
        _("Unknown"),
        _("There is some unknown thing wrong with this encryption")]
    _STATUS_ENCRYPTION = {
        "none": [
            "crypto-color-gray",
            "icon-lock-open",
            _("Not Encrypted"),
            _("This message was not encrypted. It may have been intercepted "
              "and read by an unauthorized party")],
        "decrypted": [
            "crypto-color-green",
            "icon-lock-closed",
            _("Encrypted"),
            _("This message was encrypted, great job being secure")],
        "mixed-decrypted": [
            "crypto-color-blue",
            "icon-lock-closed",
            _("Mixed Encrypted"),
            _("Part of this message were encrypted, but other parts were not "
              "encrypted")],
        "missingkey": [
            "crypto-color-red",
            "icon-lock-closed",
            _("Missing Key"),
            _("You don't have any of the private keys that will decrypt this "
              "message. Perhaps it was encrypted to an old key you don't have "
              "anymore?")],
        "mixed-missingkey": [
            "crypto-color-red",
            "icon-lock-closed",
            _("Mixed Missing Key"),
            _("Parts of the message were unable to be decrypted because you "
              "are missing the private key. Perhaps it was encrypted to an "
              "old key you don't have anymore?")],
        "error": [
            "crypto-color-red",
            "icon-lock-error",
            _("Error"),
            _("We failed to decrypt message and are unsure why.")],
        "mixed-error": [
            "crypto-color-red",
            "icon-lock-error",
            _("Mixed Error"),
            _("We failed to decrypt parts of this message and are unsure why")]
    }

    @classmethod
    def _show_message_encryption(self, status):
        # This avoids crashes when attributes are missing.
        try:
            if status.startswith('hack the planet'):
                pass
        except UndefinedError:
            status = ''

        color, icon, text, message = self._STATUS_ENCRYPTION.get(status, self._DEFAULT_ENCRYPTION)

        return {
            'color': color,
            'icon': icon,
            'text': text,
            'message': message
        }

        return classes

    @classmethod
    def _contact_url(self, person):
        if 'contact' in person['flags']:
            url = "/contact/view/" + person['address'] + "/"
        else:
            url = "/#add-contact"
        return url

    @classmethod
    def _contact_name(self, profiles, person):
        name = person['fn']
        # FIXME: bre and bnvk should discuss this :)
        #for profile in profiles:
        #    if profile['email'] == person['address']:
        #        name = profile['name']
        #        break
        return name

    URL_RE_HTTP = re.compile('(<a [^>]*?)'            # 1: <a
                             '(href=["\'])'           # 2:    href="
                             '(https?:[^>]+)'         # 3:  URL!
                             '(["\'][^>]*>)'          # 4:          ">
                             '(.*?)'                  # 5:  Description!
                             '(</a>)')                # 6: </a>

    # We deliberately leave the https:// prefix on, because it is both
    # rare and worth drawing attention to.
    URL_RE_HTTP_PROTO = re.compile('(?i)^https?://((w+\d*|[a-z]+\d+)\.)?')

    URL_RE_MAILTO = re.compile('(<a [^>]*?)'          # 1: <a
                               '(href=["\']mailto:)'  # 2:    href="mailto:
                               '([^"]+)'              # 3:  Email address!
                               '(["\'][^>]*>)'        # 4:          ">
                               '(.*?)'                # 5:  Description!
                               '(</a>)')              # 6: </a>

    URL_DANGER_ALERT = ('onclick=\'return confirm("' +
                        _("Mailpile security tip: \\n\\n"
                          "  Uh oh! This web site may be dangerous!\\n"
                          "  Are you sure you want to continue?\\n") +
                        '");\'')

    @classmethod
    def _fix_urls(self, text, truncate=45, danger=False):
        def http_fixer(m):
            url = m.group(3)
            odesc = desc = m.group(5)
            url_danger = danger

            if len(desc) > truncate:
                desc = desc[:truncate-3] + '...'
                noproto = re.sub(self.URL_RE_HTTP_PROTO, '', desc)
                if ('/' not in noproto) and ('?' not in noproto):
                    # Phishers sometimes create subdomains that look like
                    # something legit: yourbank.evil.com.
                    # So, if the domain was getting truncated reveal the TLD
                    # even if that means overflowing our truncation request.
                    noproto = re.sub(self.URL_RE_HTTP_PROTO, '', odesc)
                    if '/' in noproto:
                        desc = '.'.join(noproto.split('/')[0]
                                        .rsplit('.', 3)[-2:]) + '/...'
                    else:
                        desc = '.'.join(noproto.split('?')[0]
                                        .rsplit('.', 3)[-2:]) + '/...'
                    url_danger = True

            return ''.join([m.group(1),
                            url_danger and self.URL_DANGER_ALERT or '',
                            ' target=_blank ',
                            m.group(2), url, m.group(4), desc, m.group(6)])

        # FIXME: Disabled for now, we will instead grab the mailto: URLs
        #        using javascript. A mailto: link is a reasonable fallback
        #        until we have a GET'able compose dialog.
        #
        #def mailto_fixer(m):
        #    return ''.join([m.group(1), 'href=\'javascript:compose("',
        #                    m.group(3), '")\'>', m.group(5), m.group(6)])
        #
        #return Markup(re.sub(self.URL_RE_HTTP, http_fixer,
        #                     re.sub(self.URL_RE_MAILTO, mailto_fixer,
        #                            text)))

        return Markup(re.sub(self.URL_RE_HTTP, http_fixer, text))

    def _urlencode(self, s):
        if type(s) == 'Markup':
            s = s.unescape()
        return Markup(urllib.quote_plus(s.encode('utf-8')))

    def _safe(self, s):
        if type(s) == 'Markup':
            return s.unescape()
        else:
            return Markup(s).unescape()

    def _json(self, d):
        return self.env.session.ui.render_json(d)

    def _nice_text(self, text):
        trimmed = ''
        previous = 'not'
        for line in text.splitlines():
            if line or previous == 'not':
                trimmed += line + '\n'
                if line:
                    previous = 'not'
                else:
                    previous = 'blank'
        return trimmed.strip()

    @classmethod
    def _nice_subject(self, subject):
        output = re.sub('(?i)^((re|fw|fwd|aw|wg):\s+)+', '', subject)
        return output

    def _nice_name(self, name, truncate=100):
        if len(name) > truncate:
            name = name[:truncate-3] + '...'
        return name

    def _recipient_summary(self, editing_strings, addresses, truncate):
        summary_list = []
        recipients = editing_strings['to_aids'] + editing_strings['cc_aids'] + editing_strings['bcc_aids']
        for aid in recipients:
            summary_list.append(addresses[aid].fn)
        summary = ', '.join(summary_list)
        if len(summary) > truncate:
            others = ''
            if len(recipients) > 1:
                others = _("and") + ' ' + str(len(recipients) - 1) + ' ' + _("others")
            summary = summary[:truncate] + '... ' + others
        else:
            summary
        return summary

    def _attachment_type(self, mime):
        if mime in [
            "application/octet-stream",
            "application/mac-binhex40",
            "application/x-shockwave-flash",
            "application/x-director",
            "application/x-x509-ca-cert",
            "application/x-director",
            "application/x-msdownload",
            "application/x-director"
            ]:
            attachment = "application"
        elif mime in [
            "application/x-compress",
            "application/x-compressed",
            "application/x-tar",
            "application/zip",
            "application/x-stuffit",
            "application/x-gzip",
            "application/x-gzip-compressed",
            "application/x-tar",
            "application/x-winzip",
            "application/x-zip",
            "application/x-zip-compressed"
            ]:
            attachment = "archive"
        elif mime in [
            "audio/midi",
            "audio/mid",
            "audio/mpeg",
            "audio/basic",
            "audio/x-aiff",
            "audio/x-pn-realaudio",
            "audio/x-pn-realaudio",
            "audio/mid",
            "audio/basic",
            "audio/x-wav",
            "audio/x-mpegurl",
            "audio/wave",
            "audio/wav"
            ]:
            attachment = "audio"
        elif mime in [
            "text/x-vcard"
            ]:
            attachment = "contact"
        elif mime in [
            "image/bmp",
            "image/gif",
            "image/jpeg",
            "image/pjpeg",
            "image/svg+xml",
            "image/x-png",
            "image/png"
            ]:
            attachment = "image-visible"
        elif mime in [
            "image/cis-cod",
            "image/ief",
            "image/pipeg",
            "image/tiff",
            "image/x-cmx",
            "image/x-cmu-raster",
            "image/x-rgb",
            "image/x-icon",
            "image/x-xbitmap",
            "image/x-xpixmap",
            "image/x-xwindowdump",
            "image/x-portable-anymap",
            "image/x-portable-graymap",
            "image/x-portable-pixmap",
            "image/x-portable-bitmap",
            "application/x-photoshop",
            "application/postscript"
            ]:
            attachment = "image"
        elif mime in [
            "application/pgp-signature"
            ]:
            attachment = "signature" 
        elif mime in [
            "application/pgp-keys"
            ]:
            attachment = "keys"
        elif mime in [
            "application/rtf",
            "application/vnd.ms-works",
            "application/msword",
            "application/pdf",
            "application/x-download",
            "message/rfc822",
            "text/scriptlet",
            "text/plain",
            "text/iuls",
            "text/plain",
            "text/richtext",
            "text/x-setext",
            "text/x-component",
            "text/webviewhtml",
            "text/h323"
            ]:
            attachment = "document"
        elif mime in [
            "application/x-javascript",
            "text/html",
            "text/css",
            "text/xml",
            "text/json"
            ]:
            attachment = "code"
        elif mime in [
            "application/excel",
            "application/msexcel",
            "application/vnd.ms-excel",
            "application/vnd.msexcel",
            "application/csv",
            "application/x-csv",
            "text/tab-separated-values",
            "text/x-comma-separated-values",
            "text/comma-separated-values",
            "text/csv",
            "text/x-csv"
            ]:
            attachment = "spreadsheet"
        elif mime in [
            "application/powerpoint",
            "application/vnd.ms-powerpoint"
            ]:
            attachment = "slideshow"
        elif mime in [
            "video/quicktime",
            "video/x-sgi-movie",
            "video/mpeg",
            "video/x-la-asf",
            "video/x-ms-asf",
            "video/x-msvideo"
            ]:
            attachment = "video"
        else:
            attachment = "unknown"
        return attachment

    def _theme_settings(self):
        path, handle, mime = self.env.session.config.open_file('html_theme', 'theme.json')
        return json.load(handle)

    def _nice_fingerprint(self, fingerprint):
        if fingerprint:
            slices = [fingerprint[i:i + 4] for i in range(0, len(fingerprint), 4)]
            return slices[0] + " " + slices[1] + " " + slices[2] + " " + slices[3]
        else:
            return _("No Fingerprint")

    def _make_filter_groups(self, tags):
        split = shlex.split(tags)
        output = dict();
        add = []
        remove = []
        for item in split:
            out = item.strip('+-')
            if item[0] == "+":
                add.append(out)
            elif item[0] == "-":
                remove.append(out)
        output['add'] = add
        output['remove'] = remove
        return output
