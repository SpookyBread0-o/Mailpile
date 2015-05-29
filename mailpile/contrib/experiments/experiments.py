import copy
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText

from mailpile.crypto.state import SignatureInfo, EncryptionInfo
from mailpile.plugins import EmailTransform
from mailpile.mailutils import CleanHeaders


def _AddCryptoState(part, src=None):
    part.signature_info = src.signature_info if src else SignatureInfo()
    part.encryption_info = src.encryption_info if src else EncryptionInfo()
    return part


def _CopyAsMultipart(msg, callback, cleaner):
    m = _AddCryptoState(MIMEMultipart())
    m.set_type('multipart/mixed')
    if cleaner:
        cleaner(m)

    for hdr, value in msg.items():
        hdrl = hdr.lower()
        if not hdrl.startswith('content-') and not hdrl.startswith('mime-'):
            m[hdr] = value
            del msg[hdr]
        elif hdrl == 'mime-version':
            del msg[hdrl]
    callback('headers', m, None)

    def att(part):
        if hasattr(part, 'signature_info'):
            part.signature_info.parent = m.signature_info
            part.encryption_info.parent = m.encryption_info
        m.attach(part)
        callback('part', m, part)
    if msg.is_multipart() and msg.get_content_type() == 'multipart/mixed':
        for part in msg.get_payload():
            att(part)
    else:
        att(msg)
    callback('payload', m, None)

    return m


class EmailCryptoTxf(EmailTransform):
    """This is a set of email encryption experiments"""

    # Header protection ignores these...
    DKG_IGNORED_HEADERS = ['mime-version', 'content-type']

    # When encrypting, we may want to replace or strip certain
    # headers from the unprotected header. We also make sure some
    # of the protected headers are visible to the recipient, in
    # an inline part instead of an attachment.
    DKG_VISIBLE_HEADERS = ['subject', 'from', 'to', 'cc']
    DKG_REPLACED_HEADERS = {
        'subject': lambda s: 'Encrypted Message',
    }
    DKG_STRIPPED_HEADERS = ['openpgp']

    def DkgHeaderTransformOutgoing(self, msg, crypto_policy, cleaner):
        visible, invisible = Message(), Message()

        if 'encrypt' in crypto_policy:
            for hdr, val in CleanHeaders(msg):
                hdrl = hdr.lower()

                if hdrl in self.DKG_VISIBLE_HEADERS:
                    visible[hdr] = val
                elif hdrl not in self.DKG_IGNORED_HEADERS:
                    invisible[hdr] = val

                if hdrl in self.DKG_REPLACED_HEADERS:
                    del msg[hdr]
                    msg[hdr] = self.DKG_REPLACED_HEADERS[hdrl](val)
                elif hdrl in self.DKG_STRIPPED_HEADERS:
                    del msg[hdr]

        elif 'sign' in crypto_policy:
            for hdr, val in CleanHeaders(msg):
                if hdr.lower() not in self.DKG_IGNORED_HEADERS:
                    invisible[hdr] = val

        else:
            return msg

        def copy_callback(stage, msg, part):
            if stage == 'headers' and visible.keys():
                part = _AddCryptoState(MIMEText(visible.as_string(),
                                                'rfc822-headers'))
                part['Content-Disposition'] = 'inline'
                del part['MIME-Version']
                msg.attach(part)

            elif stage == 'payload' and invisible.keys():
                part = _AddCryptoState(MIMEText(invisible.as_string(),
                                                'rfc822-headers'))
                part['Content-Disposition'
                     ] = 'attachment; filename=Secure_Headers.txt'
                del part['MIME-Version']
                msg.attach(part)

        return _CopyAsMultipart(msg, copy_callback, cleaner)

    def DkgHeaderTransformIncoming(self, msg):
        # FIXME: Parse incoming message/rfc822-headers parts, migrate
        #        back to public header. Somehow annotate which are secure
        #        and which are not.
        return msg


    ##[ Transform hooks follow ]##############################################

    def TransformOutgoing(self, sender, rcpt, msg,
                          crypto_policy='none',
                          cleaner=lambda m: m,
                          **kwargs):
        txf_continue = True
        txf_matched = False

        if self.config.prefs.experiment_dkg_hdrs is True:
            msg = self.DkgHeaderTransformOutgoing(msg, crypto_policy, cleaner)
            txf_matched = True

        return sender, rcpt, msg, txf_matched, txf_continue

    def TransformIncoming(self, msg, **kwargs):
        txf_continue = True
        txf_matched = False

        if self.config.prefs.experiment_dkg_hdrs is True:
            msg = self.DkgHeaderTransformIncoming(msg)
            txf_matched = True

        return msg, txf_matched, txf_continue
