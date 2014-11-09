# -*- coding: utf-8 -*-
#
# debbindiff: highlight differences between two builds of Debian packages
#
# Copyright © 2014 Jérémy Bobbio <lunar@debian.org>
#
# debdindiff is free software: you can redistribute it and/or modify
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

from __future__ import print_function
import os.path
import re
import subprocess
import sys
from xml.sax.saxutils import escape
from debbindiff import logger, VERSION
from debbindiff.comparators.utils import make_temp_directory

HEADER = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="generator" content="pandoc">
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
    table.diff {
      font-size: 10pt;
    }
    .lnr {
      background-color: #ccc;
      color: #666;
    }
    .DiffChange {
      background-color: #ff8888;
      font-weight: bold;
    }
    .DiffText {
      color: white;
      background-color: #ff4444;
      font-weight: bold;
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

MAX_PAGE_SIZE = 2000 * 2 ** 10  # 2000 kB


class PrintLimitReached(Exception):
    pass


def create_limited_print_func(print_func):
    def limited_print_func(s, force=False):
        if not hasattr(limited_print_func, 'char_count'):
            limited_print_func.char_count = 0
        print_func(s)
        limited_print_func.char_count += len(s)
        if not force and limited_print_func.char_count >= MAX_PAGE_SIZE:
            raise PrintLimitReached()
    return limited_print_func


# Huge thanks to Stefaan Himpe for this solution:
# http://technogems.blogspot.com/2011/09/generate-side-by-side-diffs-in-html.html
def create_diff(lines1, lines2):
    with make_temp_directory() as temp_dir:
        path1 = os.path.join(temp_dir, 'content1')
        path2 = os.path.join(temp_dir, 'content2')
        diff_path = os.path.join(temp_dir, 'diff.html')
        with open(path1, 'w') as f:
            f.writelines(lines1)
        with open(path2, 'w') as f:
            f.writelines(lines2)
        p = subprocess.Popen(
            ['vim', '-n', '-N', '-e', '-i', 'NONE', '-u', 'NORC', '-U', 'NORC',
             '-d', path1, path2,
             '-c', 'colorscheme zellner',
             '-c', 'let g:html_number_lines=1',
             '-c', 'let g:html_use_css=1',
             '-c', 'let g:html_no_progress=1',
             '-c', 'TOhtml',
             '-c', 'w! %s' % (diff_path,),
             '-c', 'qall!',
            ], shell=False, close_fds=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        # Consume all output and wait until end of processing
        _, _ = p.communicate()
        p.wait()
        if p.returncode != 0:
            return 'vim exited with error %d' % p.returncode
        output = open(diff_path).read()
        output = re.search(r'(<table.*</table>)', output,
                           flags=re.MULTILINE | re.DOTALL).group(1)
        output = re.sub(r'<th.*</th>', '', output,
                        flags=re.MULTILINE | re.DOTALL)
        return output


def output_difference(difference, print_func):
    logger.debug('html output for %s' % (difference.source1,))
    print_func("<div class='difference'>")
    try:
        if difference.source1 == difference.source2:
            print_func("<div><span class='source'>%s</div>"
                       % escape(difference.source1))
        else:
            print_func("<div><span class='source'>%s</span> vs.</div>"
                       % escape(difference.source1))
            print_func("<div><span class='source'>%s</span></div>"
                       % escape(difference.source2))
        if difference.comment:
            print_func("<div class='comment'>%s</div>"
                       % escape(difference.comment))
        if difference.lines1 and difference.lines2:
            print_func(create_diff(difference.lines1, difference.lines2))
        for detail in difference.details:
            output_difference(detail, print_func)
    except PrintLimitReached:
        logger.debug('print limit reached')
        raise
    finally:
        print_func("</div>", force=True)


def output_header(css_url, print_func):
    if css_url:
        css_link = '<link href="%s" type="text/css" rel="stylesheet" />' % css_url
    else:
        css_link = ''
    print_func(HEADER % {'title': escape(' '.join(sys.argv)),
                         'css_link': css_link,
                        })


def output_html(differences, css_url=None, print_func=None):
    if print_func is None:
        print_func = print
    print_func = create_limited_print_func(print_func)
    try:
        output_header(css_url, print_func)
        for difference in differences:
            output_difference(difference, print_func)
    except PrintLimitReached:
        logger.debug('print limit reached')
        print_func("<div class='error'>Max output size reached.</div>",
                   force=True)
    print_func(FOOTER % {'version': VERSION}, force=True)
