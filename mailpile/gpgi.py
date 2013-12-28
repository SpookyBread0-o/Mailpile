#coding:utf-8
import os
import sys
import fcntl
import time
import re
import StringIO
import tempfile
from email.parser import Parser
from email.message import Message
from gettext import gettext as _
from subprocess import Popen, PIPE


DEFAULT_SERVER = "pool.sks-keyservers.net"

openpgp_trust = {"-": _("Trust not calculated"), 
                 "o": _("Unknown trust"),
                 "q": _("Undefined trust"),
                 "n": _("Never trust"),
                 "m": _("Marginally trust"),
                 "f": _("Full trust"),
                 "u": _("Ultimate trust"),
                 "e": _("Expired key, not trusted"),
                 "r": _("Revoked key, not trusted"),
                 "d": _("Disabled key, not trusted"),  # Deprecated flag.
                }

openpgp_algorithms = {1: _("RSA"),
                      2: _("RSA (encrypt only)"),
                      3: _("RSA (sign only)"),
                      16: _("Elgamal (encrypt only)"),
                      17: _("DSA"),
                      20: _("Elgamal (encrypt/sign) [COMPROMISED]"),
                     }
# For details on type 20 compromisation, see 
# http://lists.gnupg.org/pipermail/gnupg-announce/2003q4/000160.html

# These are detailed in the GnuPG source under doc/DETAILS.
status_messages = {
    "ENTER": [],
    "LEAVE": [],
    "ABORT": [],
    "NEWSIG": [],
    "GOODSIG": ["long_keyid_or_fpr", "username"],
    "KEYEXPIRED": ["expire_timestamp"],
    "KEYREVOKED": [],
    "BADSIG": ["long_keyid_or_fpr", "username"],
    "ERRSIG": ["long_keyid_or_fpr", "pubkey_algo", "hash_algo", "sig_class", 
               "timestamp", "rc"],
    "BADARMOR": [],
    "TRUST_UNDEFINED": ["error_token"],
    "TRUST_NEVER": ["error_token"],
    "TRUST_MARGINAL": ["zero", "validation_model"],
    "TRUST_FULLY": ["zero", "validation_model"],
    "TRUST_ULTIMATE": ["zero", "validation_model"],
    "GET_BOOL": [],
    "GET_LINE": [],
    "GET_HIDDEN": [],
    "GOT_IT": [],
    "SHM_INFO": [],
    "SHM_GET": [],
    "SHM_GET_BOOL": [],
    "SHM_GET_HIDDEN": [],
    "NEED_PASSPHRASE": ["long_main_keyid", "long_keyid", 
                        "keytype", "keylength"],
    "VALIDSIG": ["fingerprint", "sig_creation_date", "sig_timestamp", 
                 "expire_timestamp","sig_version", "reserved", "pubkey_algo", 
                 "hash_algo", "sig_class", "primary_key_fpr"],
    "SIG_ID": ["radix64_string", "sig_creation_date", "sig_timestamp"],
    "ENC_TO": ["long_keyid", "keytype", "keylength"],
    "NODATA": ["what"],
    "BAD_PASSPHRASE": ["long_keyid"],
    "NO_PUBKEY": ["long_keyid"],
    "NO_SECKEY": ["long_keyid"],
    "NEED_PASSPHRASE_SYM": ["cipher_algo", "s2k_mode", "s2k_hash"],
    "NEED_PASSPHRASE_PIN": ["card_type", "chvno", "serialno"],
    "DECRYPTION_FAILED": [],
    "DECRYPTION_OKAY": [],
    "MISSING_PASSPHRASE": [],
    "GOOD_PASSPHRASE": [],
    "GOODMDC": [],
    "BADMDC": [],
    "ERRMDC": [],
    "IMPORTED": ["long keyid", "username"],
    "IMPORT_OK": ["reason", "fingerprint"],
    "IMPORT_PROBLEM": ["reason", "fingerprint"],
    "IMPORT_CHECK": [],
    "IMPORT_RES": ["count", "no_user_id", "imported", "imported_rsa", 
                   "unchanged", "n_uids", "n_subk", "n_sigs", "n_revoc", 
                   "sec_read", "sec_imported", "sec_dups", "skipped_new_keys",
                   "not_imported"],
    "FILE_START": ["what", "filename"],
    "FILE_DONE": [],
    "FILE_ERROR": [],
    "BEGIN_DECRYPTION": ["mdc_method", "sym_algo"],
    "END_DECRYPTION": [],
    "BEGIN_ENCRYPTION": [],
    "END_ENCRYPTION": [],
    "DELETE_PROBLEM": ["reason_code"],
    "PROGRESS": ["what", "char", "cur", "total"],
    "SIG_CREATED": ["type" "pubkey algo", "hash algo", "class", 
                    "timestamp", "key fpr"],
    "SESSION_KEY": ["algo:hexdigits"],
    "NOTATION_NAME" : ["name"],
    "NOTATION_DATA" : ["string"],
    "POLICY_URL" : ["string"],
    "BEGIN_STREAM": [],
    "END_STREAM": [],
    "KEY_CREATED": ["type", "fingerprint", "handle"],
    "KEY_NOT_CREATED": ["handle"],
    "USERID_HINT": ["long main keyid", "string"],
    "UNEXPECTED": ["what"],
    "INV_RECP": ["reason", "requested_recipient"],
    "INV_SGNR": ["reason", "requested_sender"],
    "NO_RECP": ["reserved"],
    "NO_SGNR": ["reserved"],
    "ALREADY_SIGNED": ["long-keyid"], # Experimental, may disappear
    "SIGEXPIRED": [], # Deprecated but may crop up; keyexpired overrides
    "TRUNCATED": ["maxno"],
    "EXPSIG": ["long_keyid_or_fpr", "username"],
    "EXPKEYSIG": ["long_keyid_or_fpr", "username"],
    "REVKEYSIG": ["long_keyid_or_fpr", "username"],
    "ATTRIBUTE": ["fpr", "octets", "type", "index", 
                  "count", "timestamp", "expiredate", "flags"],
    "CARDCTRL": ["what", "serialno"],
    "PLAINTEXT": ["format", "timestamp", "filename"],
    "PLAINTEXT_LENGTH": ["length"],
    "SIG_SUBPACKET": ["type", "flags", "len", "data"],
    "SC_OP_SUCCESS": ["code"],
    "SC_OP_FAILURE": ["code"],
    "BACKUP_KEY_CREATED": ["fingerprint", "fname"],
    "PKA_TRUST_BAD": ["unknown"],
    "PKA_TRUST_GOOD": ["unknown"],
    "BEGIN_SIGNING": [],
    "ERROR": ["error location", "error code", "more"],
    "MOUNTPOINT": ["mdc_method", "sym_algo"],
    "SUCCESS": ["location"],
    "DECRYPTION_INFO": [],
}

del _

class EncryptionInfo(dict):
    "Contains informatin about the encryption status of a MIME part"
    def __init__(self):
        self["protocol"] = ""
        self["status"] = "none"
        self["description"] = ""
        self["have_keys"] = []
        self["missing_keys"] = []

    def __setitem__(self, item, value):
        if item == "status":
            assert(value in ["none", "decrypted", "missingkey", "error"])
        dict.__setitem__(self, item, value)


class SignatureInfo(dict):
    "Contains informatin about the signature status of a MIME part"
    def __init__(self):
        self["protocol"] = ""
        self["status"] = "none"
        self["description"] = ""
        self["from"] = ""
        self["fromaddr"] = ""
        self["timestamp"] = 0
        self["trust"] = "untrusted"

    def __setitem__(self, item, value):
        if item == "status":
            assert(value in ["none", "invalid", "unknown", "good", "error"])
        elif item == "trust":
            assert(value in ["new", "unverified", "verified", "untrusted", "expired", "revoked"])
        dict.__setitem__(self, item, value)


class GnuPG:
    """
    Wrap GnuPG and make all functionality feel Pythonic.
    """

    def __init__(self):
        self.available = None
        self.gpgbinary = 'gpg'
        self.passphrase = None
        self.fds = {"passphrase": True, 
                    "command": True, 
                    "logger": False, 
                    "status": False}
        self.handles = {}
        self.pipes = {}
        self.needed_fds = ["stdin", "stdout", "stderr", "status"]
        self.errors = []
        self.statuscallbacks = {}

    def default_errorhandler(self, *error):
        if error != "":
            self.errors.append(error)
        return True

    def default_output(self, output):
        return output

    def parse_status(self, output, *args):
        status = []
        lines = output.split("\n")
        for line in lines:
            line = line.replace("[GNUPG:] ", "")
            if line == "":
                continue
            elems = line.split(" ")
            callback_kwargs = dict(zip(status_messages, elems[1:]))
            if self.statuscallbacks.has_key(elems[0]):
                for callback in self.statuscallbacks[elems[0]]:
                    callback(*kwargs)
            status.append(elems)

        return status

    def parse_verify(self, output, *args):
        lines = output.split("\n")
        sig = {"datetime": "",
               "status": "",
               "keyid": "",
               "signer": "",
               "ok": None,
               "version": "",
               "hash": ""
              }

        if "no valid OpenPGP data found" in lines[0]:
            sig["ok"] = False
            sig["status"] = lines[1][4:]
        elif False:
            pass

        return sig

    def parse_keylist(self, keylist, *args):
        """
        >>> g = GnuPG()
        >>> v = g.parse_keylist("pub:u:4096:1:D5DC2A79C2E4AE92:2010-12-30:::\
u:Smari McCarthy <smari@immi.is>::scESC:\\nsub:u:4096:1:13E0BB42176BA0AC:\
2010-12-30::::::e:")
        >>> v.has_key("D5DC2A79C2E4AE92")
        True
        >>> v["D5DC2A79C2E4AE92"]["size"]
        4096
        >>> v["D5DC2A79C2E4AE92"]["creation-date"]
        '2010-12-30'
        >>> v["D5DC2A79C2E4AE92"]["algorithm"]
        1
        >>> v["D5DC2A79C2E4AE92"]["subkeys"][0]["algorithm"]
        1
        """
        keys = {}
        curkey = None

        def parse_pubkey(line, curkey, keys):
            keys[line[4]] = {
                "size": int(line[2]),
                "creation-date": line[5],
                "uids": [],
                "subkeys": [],
                "signatures": [],
                "trust": line[1],
                "algorithm": int(line[3])
            }
            if line[6] != "":
                keys[line[4]]["revocation-date"] = line[5]
            curkey = line[4]
            curkey, keys = parse_uid(line, curkey, keys)
            return (curkey, keys)

        def parse_subkey(line, curkey, keys):
            subkey = {"id": line[4], "size": int(line[2]), 
                      "creation-date": line[5], 
                      "algorithm": int(line[3])}
            if line[0] == "ssb":
                subkey["secret"] = True
            keys[curkey]["subkeys"].append(subkey)            
            return (curkey, keys)

        def parse_fingerprint(line, curkey, keys):
            keys[curkey]["fingerprint"] = line[9]
            return (curkey, keys)

        def parse_userattribute(line, curkey, keys):
            # TODO: We are currently ignoring user attributes as not useful.
            #       We may at some point want to use --attribute-fd and read
            #       in user photos and such?
            return (curkey, keys)

        def parse_privkey(line, curkey, keys):
            curkey, keys = parse_pubkey(line, curkey, keys)
            return (curkey, keys)

        UID_PARSE_RE = "([^\(\<]+){0,1}( \((.+)\)){0,1} (\<(.+)\>){0,1}"

        def parse_uid(line, curkey, keys):
            matches = re.match(UID_PARSE_RE, line[9])
            if matches:
                email = matches.groups(0)[4] or ""
                comment = matches.groups(0)[2] or ""
                name = matches.groups(0)[0] or ""
            else:
                email = line[9]
                name = ""
                comment = ""

            try:
                name = name.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    name = name.decode("iso-8859-1")
                except UnicodeDecodeError:
                    name = name.decode("utf-8", "replace")

            try:
                comment = comment.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    comment = comment.decode("iso-8859-1")
                except UnicodeDecodeError:
                    comment = comment.decode("utf-8", "replace")

            keys[curkey]["uids"].append({"email": email, 
                                         "name": name,
                                         "comment": comment,
                                         "creation-date": line[5] })
            return (curkey, keys)

        def parse_trust(line, curkey, keys):
            # TODO: We are currently ignoring commentary from the Trust DB.
            return (curkey, keys)

        def parse_signature(line, curkey, keys):
            sig = {"signer": line[9], "signature-date": line[5], 
                   "keyid": line[4], "trust": line[10], "algorithm": line[4]}

            keys[curkey]["signatures"].append(sig)
            return (curkey, keys)

        def parse_revoke(line, curkey, keys):
            # FIXME: Do something more to this
            print line
            return (curkey, keys)

        def parse_unknown(line, curkey, keys):
            print "Unknown line with code '%s'" % line[0]
            return (curkey, keys)

        def parse_none(line, curkey, keys):
            return (curkey, keys)

        disp = {"pub": parse_pubkey,
                "sub": parse_subkey,
                "ssb": parse_subkey,
                "fpr": parse_fingerprint,
                "uat": parse_userattribute,
                "sec": parse_privkey,
                "tru": parse_trust,
                "sig": parse_signature,
                "rev": parse_revoke,
                "uid": parse_uid,
                "gpg": parse_none,
               }

        lines = keylist.split("\n")
        for line in lines:
            if line == "":
                continue
            parms = line.split(":")
            r = disp.get(parms[0], parse_unknown)
            curkey, keys = r(parms, curkey, keys)

        return keys

    def emptycallbackmap():
        """
        Utility function for people who are confused about what callbacks 
        exist.
        """
        return dict([[x, []] for x in self.needed_fds])


    def run(self, args=[], callbacks={}, output=None, debug=False):
        """
        >>> g = GnuPG()
        >>> g.run(["--list-keys"])[0]
        0
        """
        self.pipes = {}
        args.insert(0, self.gpgbinary)
        args.insert(1, "--utf8-strings")
        args.insert(1, "--with-colons")
        args.insert(1, "--verbose")
        args.insert(1, "--batch")
        args.insert(1, "--enable-progress-filter")

        for fd in self.fds.keys():
            if fd not in self.needed_fds:
                continue
            self.pipes[fd] = os.pipe()
            if debug: 
                print "Opening fd %s, fh %d, mode %s" % (fd, 
                    self.pipes[fd][self.fds[fd]], ["r", "w"][self.fds[fd]])
            args.insert(1, "--%s-fd" % fd)
            # The remote end of the pipe:
            args.insert(2, "%d" % self.pipes[fd][not self.fds[fd]])
            fdno = self.pipes[fd][self.fds[fd]]
            self.handles[fd] = os.fdopen(fdno, ["r", "w"][self.fds[fd]])
            # Cause file handles to stay open after execing
            fcntl.fcntl(self.handles[fd], fcntl.F_SETFD, 0)
            fl = fcntl.fcntl(self.handles[fd], fcntl.F_GETFL)
            fcntl.fcntl(self.handles[fd], fcntl.F_SETFL, fl | os.O_NONBLOCK)

        if debug: print "Running gpg as: %s" % " ".join(args)

        proc = Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)

        self.handles["stdout"] = proc.stdout
        self.handles["stderr"] = proc.stderr
        self.handles["stdin"] = proc.stdin

        if output:
            self.handles["stdin"].write(output)
            self.handles["stdin"].close()

        if self.passphrase:
            self.handles["passphrase"].write(self.passphrase)
            self.handles["passphrase"].close()

        retvals = {"status": []}
        while True:
            proc.poll()

            try:
                buf = self.handles["status"].read()
                for res in self.parse_status(buf):
                    retvals["status"].append(res)
            except IOError:
                pass

            for fd in ["stdout", "stderr"]:
                if debug: print "Reading %s" % fd

                try:
                    buf = self.handles[fd].read()
                except IOError:
                    continue

                if not callbacks.has_key(fd):
                    continue

                if not retvals.has_key(fd):
                    retvals[fd] = []

                if buf == "":
                    continue

                if type(callbacks[fd]) == list:
                    for cb in callbacks[fd]:
                        retvals[fd].append(cb(buf))
                else:
                    retvals[fd].append(callbacks[fd](buf))

            if proc.returncode is not None:
                break

        return proc.returncode, retvals

    def is_available(self):
        try:
            retvals = self.run(["--version"])
            self.available = True
        except OSError:
            self.available = False

        return self.available

    def gen_key(self, name, email, passphrase):
        # FIXME: Allow for selection of alternative keyring
        #        Syntax:
        #        %%pubring mypubring.pgp
        #        %%secring mysecring.pgp
        
        batchjob = """
            %%echo starting keygen
            Key-Type: RSA
            Key-Length: 4096
            Subkey-Type: RSA
            Subkey-Length: 4096
            Name-Real: %(name)s
            Name-Email: %(email)s
            Expire-Date: 0
            Passphrase: %(passphrase)s
            %%commit
            %%echo done
        """ % {"name": name, "email": email, "passphrase": passphrase}

        returncode, retvals = self.run(["--gen-key"], output=batchjob)
        return returncode, retvals

    def list_keys(self):
        """
        >>> g = GnuPG()
        >>> g.list_keys()[0]
        0
        """
        retvals = self.run(["--list-keys", "--fingerprint"], 
                           callbacks={"stdout": self.parse_keylist})
        return retvals[1]["stdout"][0]

    def list_sigs(self):
        retvals = self.run(["--list-sigs", "--fingerprint"], 
                 callbacks={"stdout": self.parse_keylist})
        return retvals[1]["stdout"][0]

    def list_secret_keys(self):
        """
        >>> g = GnuPG()
        >>> g.list_secret_keys()[0]
        0
        """
        retvals = self.run(["--list-secret-keys", "--fingerprint"], 
                           callbacks={"stdout": self.parse_keylist})
        if retvals[1]["stdout"]:
            return retvals[1]["stdout"][0]
        else:
            return ""

    def encrypt(self, data, tokeys=[], armor=True):
        """
        >>> g = GnuPG()
        >>> g.encrypt("Hello, World", to=["smari@mailpile.is"])[0]
        0
        """
        action = ["--encrypt"]
        if armor:
            action.append("--armor")
        for r in tokeys:
            action.append("--recipient")
            action.append(r)
        retvals = self.run(action, callbacks={"stdout": self.default_output}, 
                           output=data)
        return retvals[0], retvals[1]["stdout"][0]

    def decrypt(self, data, passphrase=None):
        """
        Note that this test will fail if you don't replace the recipient with 
        one whose key you control.
        >>> g = GnuPG()
        >>> ct = g.encrypt("Hello, World", to=["smari@mailpile.is"])[1]
        >>> g.decrypt(ct)["text"]
        'Hello, World'
        """
        if passphrase:
            self.passphrase = passphrase
        action = ["--decrypt"]
        retvals = self.run(action, callbacks={"stdout": self.default_output}, 
                           output=data)
        self.passphrase = None

        encryption_info = EncryptionInfo()
        encryption_info["protocol"] = "openpgp"

        for line in retvals[1]["status"]:
            if line[0] == "DECRYPTION_FAILED":
                encryption_info["missing_keys"] = [x[1] for x in retvals[1]["status"] if x[0] == "NO_SECKEY"]
                if encryption_info["missing_keys"] == []:
                    encryption_info["status"] = "error"
                else:
                    encryption_info["status"] = "missingkey"
                text = ""
            elif line[0] == "DECRYPTION_OKAY":
                encryption_info["status"] = "decrypted"
                text = retvals[1]["stdout"][0].decode("utf-8")
            elif line[0] == "ENC_TO" and line[1] not in encryption_info["have_keys"]:
                encryption_info["have_keys"].append(line[1])
            elif line[0] == "NO_SECKEY":
                encryption_info["missing_keys"].append(line[1])
                encryption_info["have_keys"].remove(line[1])

        return encryption_info, text

    def sign(self, data, fromkey=None, armor=True, detatch=True, clearsign=False,
             passphrase=None):
        """
        >>> g = GnuPG()
        >>> g.sign("Hello, World", fromkey="smari@mailpile.is")[0]
        0
        """
        if passphrase:
            self.passphrase = passphrase
        if detatch and not clearsign:
            action = ["--detach-sign"]
        elif clearsign:
            action = ["--clearsign"]
        else:
            action = ["--sign"]
        if armor:
            action.append("--armor")
        if fromkey:
            action.append("--local-user")
            action.append(fromkey)

        retvals = self.run(action, callbacks={"stdout": self.default_output}, 
                           output=data)
        self.passphrase = None
        return retvals[0], retvals[1]["stdout"][0]

    def verify(self, data, signature=None):
        """
        >>> g = GnuPG()
        >>> s = g.sign("Hello, World", _from="smari@mailpile.is", 
            clearsign=True)[1]
        >>> g.verify(s)
        """
        params = ["--verify"]
        if signature:
            sig = tempfile.NamedTemporaryFile()
            sig.write(signature)
            sig.flush()
            params.append(sig.name)
            params.append("-")

        ret, retvals = self.run(params, 
                           callbacks={"stderr": self.parse_verify, 
                                      "status": self.parse_status}, 
                           output=data)

        signature_info = SignatureInfo()
        for line in retvals["status"]:
            if line[0] == "GOODSIG":
                signature_info["status"] = "good"
                signature_info["name"] = " ".join(line[2:-1]).decode("utf-8")
                signature_info["email"] = line[-1].strip("<>")
            elif line[0] == "BADSIG":
                signature_info["status"] = "invalid"
                signature_info["name"] = " ".join(line[2:-1]).decode("utf-8")
                signature_info["email"] = line[-1].strip("<>")
            elif line[0] == "ERRSIG":
                signature_info["status"] = "error"
                signature_info["keyinfo"] = line[1]
                signature_info["timestamp"] = int(line[5])
            elif line[0] == "EXPKEYSIG":
                signature_info["trust"] = "expired"
                signature_info["name"] = " ".join(line[2:-1]).decode("utf-8")
                signature_info["email"] = line[-1].strip("<>")
            elif line[0] in ["KEYEXPIRED", "SIGEXPIRED"]:
                signature_info["trust"] = "expired"
            elif line[0] == "REVKEYSIG":
                signature_info["trust"] = "revoked"                
                signature_info["name"] = " ".join(line[2:-1]).decode("utf-8")
                signature_info["email"] = line[-1].strip("<>")
            elif line[0] == "KEYREVOKED":
                signature_info["trust"] = "revoked"
            elif line[0] == "VALIDSIG":
                # FIXME: determine trust level, between new, unverified, verified, untrusted.
                # hardcoded to unverified for now.
                signature_info["status"] = "good"
                signature_info["trust"] = "unverified"
                signature_info["keyinfo"] = line[1]
                signature_info["timestamp"] = int(line[3])
            elif line[0] == "NO_PUBKEY":
                signature_info["status"] = "unknown"
                signature_info["trust"] = "untrusted"
            elif line[0] in ["TRUST_ULTIMATE", "TRUST_FULLY"]:
                signature_info["trust"] = "verified"

        return signature_info

    def sign_encrypt(self, data, fromkey=None, tokeys=[], armor=True, 
                     detatch=False, clearsign=True):
        retval, signblock = self.sign(data, fromkey=fromkey, armor=armor, 
                                      detatch=detatch, clearsign=clearsign)
        if detatch:
            # TODO: Deal with detached signature.
            retval, cryptblock = self.encrypt(data, tokeys=tokeys, 
                                              armor=armor)
        else:
            retval, cryptblock = self.encrypt(signblock, tokeys=tokeys, 
                                              armor=armor)

        return cryptblock

    def recv_key(self, keyid, keyserver=DEFAULT_SERVER):
        retvals = self.run(['--keyserver', keyserver, '--recv-key', keyid])
        return retvals

    def search_key(self, term, keyserver=DEFAULT_SERVER):
        retvals = self.run(['--keyserver', keyserver, '--search-key', term], debug=True)
        return retvals

    def address_to_keys(self, address):
        res = {}
        keys = self.list_keys()
        for key, props in keys.iteritems():
            if any([x["email"] == address for x in props["uids"]]):
                res[key] = props

        return res



class PGPMimeParser(Parser):

    def parse_pgpmime(self, message):
        sig_count, sig_parts, sig_alg = 0, [], 'SHA1'
        enc_count, enc_parts, enc_ver = 0, [], None

        for part in message.walk():
            mimetype = part.get_content_type()
            if (sig_count > 1) and (mimetype == 'application/pgp-signature'):
                sig = part.get_payload()
                msg = '\r\n'.join(sig_parts[0].as_string().splitlines(False))+'\r\n'

                gpg = GnuPG()
                signature_info = gpg.verify(msg, sig)

                part.signature_info = signature_info
                for sig_part in sig_parts:
                    sig_part.signature_info = signature_info

                # Reset!
                sig_count, sig_parts = 0, []

            elif sig_count > 0:
                sig_parts.append(part)
                sig_count += 1

            if enc_count > 0 and (mimetype == 'application/octet-stream'):
                crypt = tempfile.NamedTemporaryFile()
                crypt.write(part.get_payload())
                crypt.flush()
                msg = '\r\n'.join(part.as_string().splitlines(False))+'\r\n'

                gpg = GnuPG()
                encryption_info, plaintext = gpg.decrypt(msg)

                if encryption_info["status"] == "decrypted":
                    s = StringIO.StringIO()
                    s.write(plaintext)
                    s.seek(0)
                    m = Parser().parse(s)
                    part.encryption_info = encryption_info
                    part.cryptedcontainer = True
                    m.encryption_info = encryption_info
                    part.set_payload([m])

                # Reset!
                enc_count = 0

            if mimetype == 'multipart/signed':
                sig_alg = part.get_param('micalg', 'pgp-sha1'
                                         ).split('-')[-1].upper()
                sig_count = 1

            if mimetype == 'multipart/encrypted':
                enc_count = 1

    def parse(self, fp, headersonly=False):
        message = Parser.parse(self, fp, headersonly=headersonly)
        self.parse_pgpmime(message)
        return message


if __name__ == "__main__":
    g = GnuPG()
    # print g.recv_key("c903bef1")

    # print g.list_secret_keys()
    print g.address_to_keys("smari@immi.is")
    # import doctest
    # t = doctest.testmod()
    # if t.failed == 0:
    #     print "GPG Interface: All %d tests successful" % (t.attempted)
    # else:
    #     print "GPG Interface: %d out of %d tests failed" % (t.failed, t.attempted)
