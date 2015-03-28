# -*- coding: utf-8 -*-
#
# debbindiff: highlight differences between two builds of Debian packages
#
# Copyright © 2014-2015 Jérémy Bobbio <lunar@debian.org>
#           ©      2015 Reiner Herrmann <reiner@reiner-h.de>
#           © 2012-2013 Olivier Matz <zer0@droids-corp.org>
#           ©      2012 Alan De Smet <adesmet@cs.wisc.edu>
#           ©      2012 Sergey Satskiy <sergey.satskiy@gmail.com>
#           ©      2012 scito <info@scito.ch>
#
#
# debbindiff is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# debbindiff is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with debbindiff.  If not, see <http://www.gnu.org/licenses/>.
#
#
# Most of the code is borrowed from diff2html.py available at:
# http://git.droids-corp.org/?p=diff2html.git
#
# Part of the code is inspired by diff2html.rb from
# Dave Burt <dave (at) burt.id.au> (mainly for html theme)
#

from __future__ import print_function
import os.path
import htmlentitydefs
import re
import subprocess
import sys
from tempfile import NamedTemporaryFile
from xml.sax.saxutils import escape
from debbindiff import logger, VERSION
from debbindiff.comparators.utils import make_temp_directory

# minimum line size, we add a zero-sized breakable space every
# LINESIZE characters
LINESIZE = 20
TABSIZE = 8

# Characters we're willing to word wrap on
WORDBREAK = " \t;.,/):-"

DIFFON = "\x01"
DIFFOFF = "\x02"

HEADER = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="generator" content="debbindiff">
  <title>%(title)s</title>
  <style>
    body {
      background: white;
      color: black;
    }
    .footer {
      font-size: small;
    }
    .difference {
      border: outset #888 1px;
      background-color:rgba(0,0,0,.1);
      padding: 0.5em;
      margin: 0.5em 0;
    }
    .difference table {
      table-layout: fixed;
      width: 100%%;
      border: 0;
    }
    .difference th,
    .difference td {
      border: 0;
    }
    table.diff {
      border: 0px;
      border-collapse:collapse;
      font-size:0.75em;
      font-family: Lucida Console, monospace;
    }
    td.line {
      color:#8080a0
    }
    th {
      background: black;
      color: white
    }
    tr.diffunmodified td {
      background: #D0D0E0
    }
    tr.diffhunk td {
      background: #A0A0A0
    }
    tr.diffadded td {
      background: #CCFFCC
    }
    tr.diffdeleted td {
      background: #FFCCCC
    }
    tr.diffchanged td {
      background: #FFFFA0
    }
    span.diffchanged2 {
      background: #E0C880
    }
    span.diffponct {
      color: #B08080
    }
    .comment {
      font-style: italic;
    }
    .source {
      font-weight: bold;
    }
    .error {
      border: solid black 1px;
      background: red;
      color: white;
      padding: 0.2em;
    }
    .anchor {
      margin-left: 0.5em;
      font-size: 80%%;
      color: #333;
      text-decoration: none;
      display: none;
    }
    .diffheader:hover .anchor {
      display: inline;
    }
  </style>
  %(css_link)s
</head>
<body>
"""

FOOTER = """
<div class="footer">Generated by debbindiff %(version)s</div>
</body>
</html>
"""

DEFAULT_MAX_PAGE_SIZE = 2000 * 2 ** 10  # 2000 kB
MAX_DIFF_BLOCK_LINES = 50


class PrintLimitReached(Exception):
    pass


def create_limited_print_func(print_func, max_page_size):
    def limited_print_func(s, force=False):
        if not hasattr(limited_print_func, 'char_count'):
            limited_print_func.char_count = 0
        print_func(s)
        limited_print_func.char_count += len(s)
        if not force and limited_print_func.char_count >= max_page_size:
            raise PrintLimitReached()
    return limited_print_func


buf = []
add_cpt, del_cpt = 0, 0
line1, line2 = 0, 0
hunk_off1, hunk_size1, hunk_off2, hunk_size2 = 0, 0, 0, 0


def sane(x):
    r = ""
    for i in x:
        j = ord(i)
        if i not in ['\t', '\n'] and (j < 32):
            r = r + "."
        else:
            r = r + i
    return r


def linediff(s, t):
    '''
    Original line diff algorithm of diff2html. It's character based.
    '''
    if len(s):
        s = unicode(reduce(lambda x, y:x+y, [ sane(c) for c in s ]))
    if len(t):
        t = unicode(reduce(lambda x, y:x+y, [ sane(c) for c in t ]))

    m, n = len(s), len(t)
    d = [[(0, 0) for i in range(n+1)] for i in range(m+1)]


    d[0][0] = (0, (0, 0))
    for i in range(m+1)[1:]:
        d[i][0] = (i,(i-1, 0))
    for j in range(n+1)[1:]:
        d[0][j] = (j,(0, j-1))

    for i in range(m+1)[1:]:
        for j in range(n+1)[1:]:
            if s[i-1] == t[j-1]:
                cost = 0
            else:
                cost = 1
            d[i][j] = min((d[i-1][j][0] + 1, (i-1, j)),
                          (d[i][j-1][0] + 1, (i, j-1)),
                          (d[i-1][j-1][0] + cost, (i-1, j-1)))

    l = []
    coord = (m, n)
    while coord != (0, 0):
        l.insert(0, coord)
        x, y = coord
        coord = d[x][y][1]

    l1 = []
    l2 = []

    for coord in l:
        cx, cy = coord
        child_val = d[cx][cy][0]

        father_coord = d[cx][cy][1]
        fx, fy = father_coord
        father_val = d[fx][fy][0]

        diff = (cx-fx, cy-fy)

        if diff == (0, 1):
            l1.append("")
            l2.append(DIFFON + t[fy] + DIFFOFF)
        elif diff == (1, 0):
            l1.append(DIFFON + s[fx] + DIFFOFF)
            l2.append("")
        elif child_val-father_val == 1:
            l1.append(DIFFON + s[fx] + DIFFOFF)
            l2.append(DIFFON + t[fy] + DIFFOFF)
        else:
            l1.append(s[fx])
            l2.append(t[fy])

    r1, r2 = (reduce(lambda x, y:x+y, l1), reduce(lambda x, y:x+y, l2))
    return r1, r2


def convert(s, linesize=0, ponct=0):
    i = 0
    t = u""
    for c in s:
        # used by diffs
        if c == DIFFON:
            t += u'<span class="diffchanged2">'
        elif c == DIFFOFF:
            t += u"</span>"

        # special html chars
        elif htmlentitydefs.codepoint2name.has_key(ord(c)):
            t += u"&%s;" % (htmlentitydefs.codepoint2name[ord(c)])
            i += 1

        # special highlighted chars
        elif c == "\t" and ponct == 1:
            n = TABSIZE-(i%TABSIZE)
            if n == 0:
                n = TABSIZE
            t += (u'<span class="diffponct">&raquo;</span>'+'&nbsp;'*(n-1))
        elif c == " " and ponct == 1:
            t += u'<span class="diffponct">&middot;</span>'
        elif c == "\n" and ponct == 1:
            t += u'<br/><span class="diffponct">\</span>'
        else:
            t += c
            i += 1

        if linesize and (WORDBREAK.count(c) == 1):
            t += u'&#8203;'
            i = 0
        if linesize and i > linesize:
            i = 0
            t += u"&#8203;"

    return t


def output_hunk(print_func):
    print_func(u'<tr class="diffhunk"><td colspan="2">Offset %d, %d lines modified</td>'%(hunk_off1, hunk_size1))
    print_func(u'<td colspan="2">Offset %d, %d lines modified</td></tr>\n'%(hunk_off2, hunk_size2))


def output_line(print_func, s1, s2):
    global line1
    global line2

    orig1 = s1
    orig2 = s2

    if s1 == None and s2 == None:
        type_name = "unmodified"
    elif s1 == "" and s2 == "":
        type_name = "unmodified"
    elif s1 == None or s1 == "":
        type_name = "added"
    elif s2 == None or s2 == "":
        type_name = "deleted"
    elif s1 == s2 and not s1.endswith('lines removed ]') and not s2.endswith('lines removed ]'):
        type_name = "unmodified"
    else:
        type_name = "changed"
        s1, s2 = linediff(orig1, orig2)

    print_func(u'<tr class="diff%s">' % type_name)
    try:
        if s1 is not None:
            print_func(u'<td class="diffline">%d </td>' % line1)
            print_func(u'<td class="diffpresent">')
            print_func(convert(s1, linesize=LINESIZE, ponct=1))
            print_func(u'</td>')
        else:
            s1 = ""
            print_func(u'<td colspan="2">&nbsp;</td>')

        if s2 is not None:
            print_func(u'<td class="diffline">%d </td>' % line2)
            print_func(u'<td class="diffpresent">')
            print_func(convert(s2, linesize=LINESIZE, ponct=1))
            print_func(u'</td>')
        else:
            s2 = ""
            print_func(u'<td colspan="2">&nbsp;</td>')
    finally:
        print_func(u"</tr>\n", force=True)

    m = orig1 and re.match(r"^\[ (\d+) lines removed \]$", orig1)
    if m:
        line1 += int(m.group(1))
    elif orig1 is not None:
        line1 += 1
    m = orig2 and re.match(r"^\[ (\d+) lines removed \]$", orig2)
    if m:
        line2 += int(m.group(1))
    elif orig2 is not None:
        line2 += 1


def empty_buffer(print_func):
    global buf
    global add_cpt
    global del_cpt

    if del_cpt == 0 or add_cpt == 0:
        for l in buf:
            output_line(print_func, l[0], l[1])

    elif del_cpt != 0 and add_cpt != 0:
        l0, l1 = [], []
        for l in buf:
            if l[0] != None:
                l0.append(l[0])
            if l[1] != None:
                l1.append(l[1])
        max_len = (len(l0) > len(l1)) and len(l0) or len(l1)
        for i in range(max_len):
            s0, s1 = "", ""
            if i < len(l0):
                s0 = l0[i]
            if i < len(l1):
                s1 = l1[i]
            output_line(print_func, s0, s1)

    add_cpt, del_cpt = 0, 0
    buf = []


def output_unified_diff(print_func, unified_diff):
    global add_cpt, del_cpt
    global line1, line2
    global hunk_off1, hunk_size1, hunk_off2, hunk_size2

    print_func(u'<table class="diff">\n')
    try:
        print_func(u'<colgroup><col style="width: 3em;"/><col style="99%"/>\n')
        print_func(u'<col style="width: 3em;"/><col style="99%"/></colgroup>\n')

        for l in unified_diff.splitlines():
            m = re.match(r'^--- ([^\s]*)', l)
            if m:
                empty_buffer(print_func)
                continue
            m = re.match(r'^\+\+\+ ([^\s]*)', l)
            if m:
                empty_buffer(print_func)
                continue

            m = re.match(r"@@ -(\d+),?(\d*) \+(\d+),?(\d*)", l)
            if m:
                empty_buffer(print_func)
                hunk_data = map(lambda x:x=="" and 1 or int(x), m.groups())
                hunk_off1, hunk_size1, hunk_off2, hunk_size2 = hunk_data
                line1, line2 = hunk_off1, hunk_off2
                output_hunk(print_func)
                continue

            if re.match(r"^\\ No newline", l):
                if hunk_size2 == 0:
                    buf[-1] = (buf[-1][0], buf[-1][1] + '\n' + l[2:])
                else:
                    buf[-1] = (buf[-1][0] + '\n' + l[2:], buf[-1][1])
                continue

            if hunk_size1 <= 0 and hunk_size2 <= 0:
                empty_buffer(print_func)
                continue

            m = re.match(r"^\+\[ (\d+) lines removed \]$", l)
            if m:
                add_cpt += int(m.group(1))
                hunk_size2 -= int(m.group(1))
                buf.append((None, l[1:]))
                continue

            if re.match(r"^\+", l):
                add_cpt += 1
                hunk_size2 -= 1
                buf.append((None, l[1:]))
                continue

            m = re.match(r"^-\[ (\d+) lines removed \]$", l)
            if m:
                del_cpt += int(m.group(1))
                hunk_size1 -= int(m.group(1))
                buf.append((l[1:], None))
                continue

            if re.match(r"^-", l):
                del_cpt += 1
                hunk_size1 -= 1
                buf.append((l[1:], None))
                continue

            if re.match(r"^ ", l) and hunk_size1 and hunk_size2:
                empty_buffer(print_func)
                hunk_size1 -= 1
                hunk_size2 -= 1
                buf.append((l[1:], l[1:]))
                continue

            empty_buffer(print_func)

        empty_buffer(print_func)
    finally:
        print_func(u"</table>", force=True)


def output_difference(difference, print_func, parents):
    logger.debug('html output for %s', difference.source1)
    sources = parents + [difference.source1]
    print_func(u"<div class='difference'>")
    try:
        print_func(u"<div class='diffheader'>")
        if difference.source1 == difference.source2:
            print_func(u"<div><span class='source'>%s<span>"
                       % escape(difference.source1))
        else:
            print_func(u"<div><span class='source'>%s</span> vs.</div>"
                       % escape(difference.source1))
            print_func(u"<div><span class='source'>%s</span>"
                       % escape(difference.source2))
        anchor = '/'.join(sources[1:])
        print_func(u" <a class='anchor' href='#%s' name='%s'>&para;</a>" % (anchor, anchor))
        print_func(u"</div>")
        if difference.comment:
            print_func(u"<div class='comment'>%s</div>"
                       % escape(difference.comment).replace('\n', '<br />'))
        print_func(u"</div>")
        if difference.unified_diff:
            output_unified_diff(print_func, difference.unified_diff)
        for detail in difference.details:
            output_difference(detail, print_func, sources)
    except PrintLimitReached:
        logger.debug('print limit reached')
        raise
    finally:
        print_func(u"</div>", force=True)


def output_header(css_url, print_func):
    if css_url:
        css_link = '<link href="%s" type="text/css" rel="stylesheet" />' % css_url
    else:
        css_link = ''
    print_func(HEADER % {'title': escape(' '.join(sys.argv)),
                         'css_link': css_link,
                        })


def output_html(differences, css_url=None, print_func=None, max_page_size=None):
    if print_func is None:
        print_func = print
    if max_page_size is None:
        max_page_size = DEFAULT_MAX_PAGE_SIZE
    print_func = create_limited_print_func(print_func, max_page_size)
    try:
        output_header(css_url, print_func)
        for difference in differences:
            output_difference(difference, print_func, [])
    except PrintLimitReached:
        logger.debug('print limit reached')
        print_func(u"<div class='error'>Max output size reached.</div>",
                   force=True)
    print_func(FOOTER % {'version': VERSION}, force=True)
