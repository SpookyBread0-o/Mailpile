import time
import datetime
import mailpile.plugins


##[ Keywords ]################################################################

def meta_kw_extractor(index, msg_mid, msg, msg_date):
    mdate = datetime.date.fromtimestamp(msg_date)
    keywords = [
        '%s:year' % mdate.year,
        '%s:month' % mdate.month,
        '%s:day' % mdate.day,
        '%s-%s:yearmonth' % (mdate.year, mdate.month),
        '%s-%s-%s:date' % (mdate.year, mdate.month, mdate.day)
    ]
    return keywords

mailpile.plugins.register_meta_kw_extractor('dates', meta_kw_extractor)


##[ Search terms ]############################################################

def _adjust(d):
    if d[2] > 31:
        d[1] += 1
        d[2] -= 31
    if d[1] > 12:
        d[0] += 1
        d[1] -= 12

def _mk_date(ts):
    mdate = datetime.date.fromtimestamp(ts)
    return '%d-%d-%d' % (mdate.year, mdate.month, mdate.day)

_date_offsets = {
    'today': 0,
    'yesterday': 1
}
def search(config, idx, term, hits):
    try:
        word = term.split(':', 1)[1].lower()
        if '..' in term:
            start, end = word.split('..')
        else:
            start = end = word

        if start in _date_offsets:
            start = _mk_date(time.time() - _date_offsets[start]*24*3600)
        if end in _date_offsets:
            end = _mk_date(time.time() - _date_offsets[end]*24*3600)

        start = [int(p) for p in start.split('-')][:3]
        end = [int(p) for p in end.split('-')[:3]]
        while len(start) < 3:
            start.append(1)
        if len(end) == 1:
            end.extend([12, 31])
        elif len(end) == 2:
            end.append(31)
        if not start <= end:
            raise ValueError()

        terms = []
        while start <= end:
            # Move forward one year?
            if start[1:] == [1, 1]:
                ny = [start[0], 12, 31]
                if ny <= end:
                    terms.append('%d:year' % start[0])
                    start[0] += 1
                    continue

            # Move forward one month?
            if start[2] == 1:
                nm = [start[0], start[1], 31]
                if nm <= end:
                    terms.append('%d-%d:yearmonth' % (start[0], start[1]))
                    start[1] += 1
                    _adjust(start)
                    continue

            # Move forward one day...
            terms.append('%d-%d-%d:date' % tuple(start))
            start[2] += 1
            _adjust(start)

        rt = []
        for term in terms:
            rt.extend(hits(term))
        return rt
    except:
        raise ValueError('Invalid date range: %s' % term)

mailpile.plugins.register_search_term('dates', search)
mailpile.plugins.register_search_term('date', search)
