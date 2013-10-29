import datetime
import re
import time

import mailpile.plugins
from mailpile.commands import Command
from mailpile.mailutils import Email, ExtractEmails
from mailpile.search import MailIndex
from mailpile.util import *

from mailpile.plugins.search import Search



class NetworkGraph(Search):
    """Get a graph of the network in the current search results."""
    ORDER = ('Searching', 1)
    SYNOPSIS = ('n', 'shownetwork', 'shownetwork', '<terms>')
    HTTP_CALLABLE = ('GET', )

    def command(self, search=None):
        session, idx, start, num = self._do_search(search=search)

        nodes = []
        links = []
        res = {}

        for messageid in session.results:
            msg = self._idx().get_msg_at_idx_pos(messageid)
            msgfrom = msg[self._idx().MSG_FROM]
            msgto = [self._idx().EMAILS[int(x, 36)] for x in msg[self._idx().MSG_TO].split(",") if x != ""]
            m = re.match("((.*) ){0,1}\<(.*)\>", msgfrom)
            if m:
                name = m.groups(0)[1]
                email = m.groups(0)[2]
            else:
                name = None
                email = msgfrom

            if email not in [m["email"] for m in nodes]:
                n = {"email": email}
                if name: n["name"] = name
                nodes.append(n)

            for address in msgto:
                if address not in [m["email"] for m in nodes]:
                    nodes.append({"email": address})

            curnodes = [x["email"] for x in nodes]
            fromid = curnodes.index(email)
            searchspace = [m for m in links if m["source"] == fromid]
            for address in msgto:
                index = curnodes.index(address)
                link = [m for m in searchspace if m["target"] == index]
                if len(link) == 0:
                    links.append({"source": fromid, "target": index, "value": 1})
                elif len(link) == 1:
                    link[0]["value"] += 1
                else:
                    raise ValueError("Too many links! - This should never happen.")

            if len(nodes) >= 300:
                # Let's put a hard upper limit on how many nodes we can have, for performance reasons.
                # There might be a better way to do this though...
                res["limit_hit"] = True
                break

        res["nodes"] = nodes
        res["links"] = links
        res["searched"] = session.searched
        if not res.has_key("limit_hit"):
            res["limit_hit"] = False
        return res


mailpile.plugins.register_commands(NetworkGraph)
