import sys
import os
import re
import json
import unicodedata
import urllib.parse

# ==========================================
# 1. Unicode & Regular Expression Precomputations
# ==========================================

# Collect BMP characters that belong to punctuation or symbol categories
P_S_chars = []
for i in range(0x10000):
    c = chr(i)
    cat = unicodedata.category(c)
    if cat.startswith('P') or cat.startswith('S'):
        P_S_chars.append(c)

P_S_chars_no_tilde = [c for c in P_S_chars if c != '~']

def make_class(chars, negate=False, extra=""):
    escaped = "".join(re.escape(c) for c in chars)
    return f"[^{escaped}{extra}]" if negate else f"[{escaped}{extra}]"

_punctuation = make_class(P_S_chars)
_punctuationOrSpace = make_class(P_S_chars, extra="\\s")
_notPunctuationOrSpace = make_class(P_S_chars, negate=True, extra="\\s")

_punctuationGfmStrongEm = make_class(P_S_chars_no_tilde)
_punctuationOrSpaceGfmStrongEm = make_class(P_S_chars_no_tilde, extra="\\s")
_notPunctuationOrSpaceGfmStrongEm = make_class(P_S_chars_no_tilde, negate=True, extra="\\s")

class Edit:
    def __init__(self, pattern, flags=0):
        if isinstance(pattern, Edit):
            self.pattern = pattern.pattern
            self.flags = pattern.flags
        elif hasattr(pattern, 'pattern'):
            self.pattern = pattern.pattern
            self.flags = pattern.flags
        else:
            self.pattern = pattern
            self.flags = flags

    def replace(self, old, new):
        old_str = old.pattern if hasattr(old, 'pattern') else str(old)
        new_str = new.pattern if hasattr(new, 'pattern') else str(new)
        
        # Remove caret anchor unless preceded by [
        new_str = re.sub(r'(^|[^\[])\^', r'\1', new_str)
        self.pattern = self.pattern.replace(old_str, new_str)
        return self

    def getRegex(self, extra_flags=0):
        return re.compile(self.pattern, self.flags | extra_flags)

def cachedIndentRegex(createRegex):
    cache = {}
    def get_regex(indent):
        cacheIndex = max(0, min(3, indent - 1))
        if cacheIndex not in cache:
            cache[cacheIndex] = createRegex(cacheIndex)
        return cache[cacheIndex]
    return get_regex

def listItemRegex(bull):
    return re.compile(r'^( {0,3}' + bull + r')((?:[\t ][^\n]*)?(?:\n|$))')


nextBulletRegex = cachedIndentRegex(lambda indent: re.compile(f"^ {{0,{indent}}}(?:[*+-]|\\d{{1,9}}[.)])((?:[ \t][^\\n]*)?(?:\\n|$))"))
hrRegex = cachedIndentRegex(lambda indent: re.compile(f"^ {{0,{indent}}}((?:- *){{3,}}|(?:_ *){{3,}}|\\*(?:\\* *){{2,}})(?:\\n+|$)"))
fencesBeginRegex = cachedIndentRegex(lambda indent: re.compile(f"^ {{0,{indent}}}(?:```|~~~)"))
headingBeginRegex = cachedIndentRegex(lambda indent: re.compile(f"^ {{0,{indent}}}#"))
htmlBeginRegex = cachedIndentRegex(lambda indent: re.compile(f"^ {{0,{indent}}}<(?:[a-z].*>|!--)", re.IGNORECASE))
blockquoteBeginRegex = cachedIndentRegex(lambda indent: re.compile(f"^ {{0,{indent}}}>"))

noopTest = re.compile(r'(?!)')

# ==========================================
# 2. Grammar Rules Definitions
# ==========================================

other = {
    'codeRemoveIndent': re.compile(r'^(?: {1,4}| {0,3}\t)', re.MULTILINE),
    'outputLinkReplace': re.compile(r'\\([\[\]])'),
    'indentCodeCompensation': re.compile(r'^(\s+)(?:```)'),
    'beginningSpace': re.compile(r'^\s+'),
    'endingHash': re.compile(r'#$'),
    'startingSpaceChar': re.compile(r'^ '),
    'endingSpaceChar': re.compile(r' $'),
    'nonSpaceChar': re.compile(r'[^ ]'),
    'newLineCharGlobal': re.compile(r'\n'),
    'tabCharGlobal': re.compile(r'\t'),
    'multipleSpaceGlobal': re.compile(r'\s+'),
    'blankLine': re.compile(r'^[ \t]*$'),
    'doubleBlankLine': re.compile(r'\n[ \t]*\n[ \t]*$'),
    'blockquoteStart': re.compile(r'^ {0,3}>'),
    'blockquoteSetextReplace': re.compile(r'\n {0,3}((?:=+|-+) *)(?=\n|$)'),
    'blockquoteSetextReplace2': re.compile(r'^ {0,3}>[ \t]?', re.MULTILINE),
    'listReplaceNesting': re.compile(r'^ {1,4}(?=( {4})*[^ ])'),
    'listIsTask': re.compile(r'^\[[ xX]\] +\S'),
    'listReplaceTask': re.compile(r'^\[[ xX]\] +'),
    'listTaskCheckbox': re.compile(r'\[[ xX]\]'),
    'anyLine': re.compile(r'\n.*\n'),
    'hrefBrackets': re.compile(r'^<(.*)>$'),
    'tableDelimiter': re.compile(r'[:|]'),
    'tableAlignChars': re.compile(r'^\||\| *$'),
    'tableRowBlankLine': re.compile(r'\n[ \t]*$'),
    'tableAlignRight': re.compile(r'^ *-+: *$'),
    'tableAlignCenter': re.compile(r'^ *:-+: *$'),
    'tableAlignLeft': re.compile(r'^ *:-+ *$'),
    'startATag': re.compile(r'^<a ', re.IGNORECASE),
    'endATag': re.compile(r'^<\/a>', re.IGNORECASE),
    'startPreScriptTag': re.compile(r'^<(pre|code|kbd|script)(\s|>)', re.IGNORECASE),
    'endPreScriptTag': re.compile(r'^<\/(pre|code|kbd|script)(\s|>)', re.IGNORECASE),
    'startAngleBracket': re.compile(r'^<'),
    'endAngleBracket': re.compile(r'>$'),
    'pedanticHrefTitle': re.compile(r"^([^'\"]*[^\s])\s+(['\"])(.*)\2"),
    'unicodeAlphaNumeric': re.compile(r'[^\W_]'),
    'escapeTest': re.compile(r'[&<>"\']'),
    'escapeReplace': re.compile(r'[&<>"\']'),
    'escapeTestNoEncode': re.compile(r'[<>"\']|&(?!(#\d{1,7}|#[Xx][a-fA-F0-9]{1,6}|\w+);)'),
    'escapeReplaceNoEncode': re.compile(r'[<>"\']|&(?!(#\d{1,7}|#[Xx][a-fA-F0-9]{1,6}|\w+);)'),
    'caret': re.compile(r'(^|[^\[])\^'),
    'percentDecode': re.compile(r'%25'),
    'findPipe': re.compile(r'\|'),
    'splitPipe': re.compile(r' \|'),
    'slashPipe': re.compile(r'\\\|'),
    'carriageReturn': re.compile(r'\r\n|\r'),
    'spaceLine': re.compile(r'^ +$', re.MULTILINE),
    'notSpaceStart': re.compile(r'^\S*'),
    'endingNewline': re.compile(r'\n$')
}

newline = re.compile(r'^(?:[ \t]*(?:\n|$))+')
blockCode = re.compile(r'^((?: {4}| {0,3}\t)[^\n]+(?:\n(?:[ \t]*(?:\n|$))*)?)+')
fences = re.compile(r'^ {0,3}(`{3,}(?=[^`\n]*(?:\n|$))|~{3,})([^\n]*)(?:\n|$)(?:|([\s\S]*?)(?:\n|$))(?: {0,3}\1[~`]* *(?=\n|$)|$)')
hr = re.compile(r'^ {0,3}((?:-[\t ]*){3,}|(?:_[ \t]*){3,}|(?:\*[ \t]*){3,})(?:\n+|$)')
heading = re.compile(r'^ {0,3}(#{1,6})(?=\s|$)(.*)(?:\n+|$)')
bullet = re.compile(r' {0,3}(?:[*+-]|\d{1,9}[.)])')
lheadingCore = re.compile(r'^(?!bull |blockCode|fences|blockquote|heading|html|table)((?:.|\n(?!\s*?\n|bull |blockCode|fences|blockquote|heading|html|table))+?)\n {0,3}(=+|-+) *(?:\n+|$)')

lheading = Edit(lheadingCore).replace('bull', bullet).replace('blockCode', r'(?: {4}| {0,3}\t)').replace('fences', r' {0,3}(?:`{3,}|~{3,})').replace('blockquote', r' {0,3}>').replace('heading', r' {0,3}#{1,6}').replace('html', r' {0,3}<[^\n>]+>\n').replace('|table', '').getRegex()
lheadingGfm = Edit(lheadingCore).replace('bull', bullet).replace('blockCode', r'(?: {4}| {0,3}\t)').replace('fences', r' {0,3}(?:`{3,}|~{3,})').replace('blockquote', r' {0,3}>').replace('heading', r' {0,3}#{1,6}').replace('html', r' {0,3}<[^\n>]+>\n').replace('table', r' {0,3}\|?(?:[:\- ]*\|)+[\:\- ]*\n').getRegex()

_paragraph = re.compile(r'^([^\n]+(?:\n(?!hr|heading|lheading|blockquote|fences|list|html|table| +\n)[^\n]+)*)')
blockText = re.compile(r'^[^\n]+')
_blockLabel = re.compile(r'(?!\s*\])(?:\\[\s\S]|[^\[\]\\])+')

def_pat = Edit(r'^ {0,3}\[(label)\]: *(?:\n[ \t]*)?([^<\s][^\s]*|<.*?>)(?:(?: +(?:\n[ \t]*)?| *\n[ \t]*)(title))? *(?:\n+|$)').replace('label', _blockLabel).replace('title', r'(?:"(?:\\"?|[^"\\])*"|\'[^\'\n]*(?:\n[^\'\n]+)*\n?\'|\([^()]*\))').getRegex()
list_pat = Edit(r'^(bull)([ \t][^\n]*?)?(?:\n|$)').replace('bull', bullet).getRegex()

_tag = 'address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|meta|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul'
_comment = re.compile(r'<!--(?:-?>|[\s\S]*?(?:-->|$))')

html = Edit(
  '^ {0,3}(?:'
  + '<(script|pre|style|textarea)[\\s>][\\s\\S]*?(?:</\\1>[^\\n]*\\n+|$)'
  + '|comment[^\\n]*(\\n+|$)'
  + '|<\\?[\\s\\S]*?(?:\\?>[^\\n]*\\n*|$)'
  + '|<![A-Z][\\s\\S]*?(?:>[^\\n]*\\n*|$)'
  + '|<!\\[CDATA\\[[\\s\\S]*?(?:\\]\\]>[^\\n]*\\n*|$)'
  + '|</?(tag)(?: +|\\n|/?>)[\\s\\S]*?(?:(?:\\n[ \t]*)+\\n|$)'
  + '|<(?!script|pre|style|textarea)([a-z][\\w-]*)(?:attribute)*? */?>(?=[ \\t]*(?:\\n|$))[\\s\\S]*?(?:(?:\\n[ \t]*)+\\n|$)'
  + '|</(?!script|pre|style|textarea)[a-z][\\w-]*\\s*>(?=[ \\t]*(?:\\n|$))[\\s\\S]*?(?:(?:\\n[ \t]*)+\\n|$)'
  + ')', re.IGNORECASE).replace('comment', _comment).replace('tag', _tag).replace('attribute', " +[a-zA-Z:_][\\w.:-]*(?: *= *\"[^\"\\n]*\"| *= *'[^'\\n]*'| *= *[^\\s\"'=<>`]+)?").getRegex()


paragraph = Edit(_paragraph).replace('hr', hr).replace('heading', r' {0,3}#{1,6}(?:\s|$)').replace('|lheading', '').replace('|table', '').replace('blockquote', r' {0,3}>').replace('fences', r' {0,3}(?:`{3,}(?=[^`\n]*\n)|~{3,})[^\\n]*\n').replace('list', r' {0,3}(?:[*+-]|1[.)])[ \t]+[^ \t\n]').replace('html', r'</?(?:tag)(?: +|\\n|/?>)|<(?:script|pre|style|textarea|!--)').replace('tag', _tag).getRegex()

blockquote = Edit(r'^( {0,3}> ?(paragraph|[^\n]*)(?:\n|$))+').replace('paragraph', paragraph).getRegex()

blockNormal = {
    'blockquote': blockquote,
    'code': blockCode,
    'def': def_pat,
    'fences': fences,
    'heading': heading,
    'hr': hr,
    'html': html,
    'lheading': lheading,
    'list': list_pat,
    'newline': newline,
    'paragraph': paragraph,
    'table': noopTest,
    'text': blockText
}

gfmTable = Edit(r'^ *([^\n ].*)\n {0,3}((?:\| *)?:?-+:? *(?:\| *:?-+:? *)*(?:\| *)?)(?:\n((?:(?! *\n|hr|heading|blockquote|code|fences|list|html).*(?:\n|$))*)\n*|$)').replace('hr', hr).replace('heading', r' {0,3}#{1,6}(?:\s|$)').replace('blockquote', r' {0,3}>').replace('code', r'(?: {4}| {0,3}\t)[^\n]').replace('fences', r' {0,3}(?:`{3,}(?=[^`\n]*\n)|~{3,})[^\\n]*\n').replace('list', r' {0,3}(?:[*+-]|1[.)])[ \t]').replace('html', r'</?(?:tag)(?: +|\\n|/?>)|<(?:script|pre|style|textarea|!--)').replace('tag', _tag).getRegex()

blockGfm = {
    **blockNormal,
    'lheading': lheadingGfm,
    'table': gfmTable,
    'paragraph': Edit(_paragraph).replace('hr', hr).replace('heading', r' {0,3}#{1,6}(?:\s|$)').replace('|lheading', '').replace('table', gfmTable).replace('blockquote', r' {0,3}>').replace('fences', r' {0,3}(?:`{3,}(?=[^`\n]*\n)|~{3,})[^\\n]*\n').replace('list', r' {0,3}(?:[*+-]|1[.)])[ \t]+[^ \t\n]').replace('html', r'</?(?:tag)(?: +|\\n|/?>)|<(?:script|pre|style|textarea|!--)').replace('tag', _tag).getRegex()
}

blockPedantic = {
    **blockNormal,
    'html': Edit(r'^ *(?:comment *(?:\n|\s*$)|<(tag)[\s\S]+?</\1> *(?:\n{2,}|\s*$)|<tag(?:"[^"]*"|\'[^\']*\'|\s[^\'"/>\s]*)*?/?> *(?:\n{2,}|\s*$))').replace('comment', _comment).replace('tag', '(?!(?:a|em|strong|small|s|cite|q|dfn|abbr|data|time|code|var|samp|kbd|sub|sup|i|b|u|mark|ruby|rt|rp|bdi|bdo|span|br|wbr|ins|del|img)\\b)\\w+(?!:|[^\\w\\s@]*@)\\b').getRegex(),
    'def': re.compile(r'^ *\[([^\]]+)\]: *<?([^\s>]+)>?(?: +(["(][^\n]+[")]))? *(?:\n+|$)'),
    'heading': re.compile(r'^(#{1,6})(.*)(?:\n+|$)'),
    'fences': noopTest,
    'lheading': re.compile(r'^(.+?)\n {0,3}(=+|-+) *(?:\n+|$)'),
    'paragraph': Edit(_paragraph).replace('hr', hr).replace('heading', r' *#{1,6} *[^\n]').replace('lheading', lheading).replace('|table', '').replace('blockquote', r' {0,3}>').replace('|fences', '').replace('|list', '').replace('|html', '').replace('|tag', '').getRegex()
}

escape = re.compile(r'^\\([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~])')
inlineCode = re.compile(r'^(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)')
br_pat = re.compile(r'^( {2,}|\\)\n(?!\s*$)')
inlineText = re.compile(r'^(`+|[^`])(?:(?= {2,}\n)|[\s\S]*?(?:(?=[\\<!\[`*_]|\b_|$)|[^ ](?= {2,}\n)))')

punctuation = Edit(r'^((?![*_])punctSpace)').replace('punctSpace', _punctuationOrSpace).getRegex()

blockSkip = Edit(r'link|precode-code|html').replace('link', r'\[(?:[^\[\]`]|(?P<a>`+)[^`]+(?P=a)(?!`))*?\]\((?:\\[\s\S]|[^\\\(\)]|\((?:\\[\s\S]|[^\\\(\)])*\))*\)').replace('precode-', '(?<!`)()').replace('code', r'(?P<b>`+)[^`]+(?P=b)(?!`)').replace('html', r'<(?! )[^<>]*?>').getRegex()


emStrongLDelimCore = r'^(?:\*+(?:((?!\*)punct)|([^\s*]))?)|^_+(?:((?!_)punct)|([^\s_]))?'
emStrongLDelim = Edit(emStrongLDelimCore).replace('punct', _punctuation).getRegex()
emStrongLDelimGfm = Edit(emStrongLDelimCore).replace('punct', _punctuationGfmStrongEm).getRegex()

emStrongRDelimAstCore = (
    r'^[^_*]*?__[^_*]*?\\*[^_*]*?(?=__)'
    r'|[^*]+(?=[^*])'
    r'|(?!\*)punct(\*+)(?=[\s]|$)'
    r'|notPunctSpace(\*+)(?!\*)(?=punctSpace|$)'
    r'|(?!\*)punctSpace(\*+)(?=notPunctSpace)'
    r'|[\s](\*+)(?!\*)(?=punct)'
    r'|(?!\*)punct(\*+)(?!\*)(?=punct)'
    r'|notPunctSpace(\*+)(?=notPunctSpace)'
)
emStrongRDelimAst = Edit(emStrongRDelimAstCore).replace('notPunctSpace', _notPunctuationOrSpace).replace('punctSpace', _punctuationOrSpace).replace('punct', _punctuation).getRegex()
emStrongRDelimAstGfm = Edit(emStrongRDelimAstCore).replace('notPunctSpace', _notPunctuationOrSpaceGfmStrongEm).replace('punctSpace', _punctuationOrSpaceGfmStrongEm).replace('punct', _punctuationGfmStrongEm).getRegex()

emStrongRDelimUndCore = (
    r'^[^_*]*?\*\*[^_*]*?_[^_*]*?(?=\*\*)'
    r'|[^_]+(?=[^_])'
    r'|(?!_)punct(_+)(?=[\s]|$)'
    r'|notPunctSpace(_+)(?!_)(?=punctSpace|$)'
    r'|(?!_)punctSpace(_+)(?=notPunctSpace)'
    r'|[\s](_+)(?!_)(?=punct)'
    r'|(?!_)punct(_+)(?!_)(?=punct)'
)
emStrongRDelimUnd = Edit(emStrongRDelimUndCore).replace('notPunctSpace', _notPunctuationOrSpace).replace('punctSpace', _punctuationOrSpace).replace('punct', _punctuation).getRegex()

delLDelim = Edit(r'^~~?(?:((?!~)punct)|[^\s~])').replace('punct', _punctuation).getRegex()

delRDelimCore = (
    r'^[^~]+(?=[^~])'
    r'|(?!~)punct(~~?)(?=[\s]|$)'
    r'|notPunctSpace(~~?)(?!~)(?=punctSpace|$)'
    r'|(?!~)punctSpace(~~?)(?=notPunctSpace)'
    r'|[\s](~~?)(?!~)(?=punct)'
    r'|(?!~)punct(~~?)(?!~)(?=punct)'
    r'|notPunctSpace(~~?)(?=notPunctSpace)'
)
delRDelim = Edit(delRDelimCore).replace('notPunctSpace', _notPunctuationOrSpace).replace('punctSpace', _punctuationOrSpace).replace('punct', _punctuation).getRegex()

anyPunctuation = Edit(r'\\(punct)').replace('punct', _punctuation).getRegex()

autolink = Edit(r'^<(scheme:[^\s\x00-\x1f<>]*|email)>').replace('scheme', r'[a-zA-Z][a-zA-Z0-9+.-]{1,31}').replace('email', r'[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+(@)[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+(?![-_])').getRegex()

_inlineComment = Edit(_comment).replace('(?:-->|$)', '-->').getRegex()
tag = Edit(r'^comment|^</[a-zA-Z][\w:-]*\s*>|^<[a-zA-Z][\w-]*(?:attribute)*?\s*/?>|^<\?[\s\S]*?\?>|^<![a-zA-Z]+\s[\s\S]*?>|^<!\[CDATA\[[\s\S]*?\]\]>').replace('comment', _inlineComment).replace('attribute', r'\s+[a-zA-Z:_][\w.:-]*(?:\s*=\s*"[^"]*"|\s*=\s*\'[^\']*\'|\s*=\s*[^\s"\'=<>`]+)?').getRegex()

_inlineLabel = re.compile(r'(?:\[(?:\\[\s\S]|[^\[\]\\])*\]|\\[\s\S]|`+(?!`)[^`]*?`+(?!`)|``+(?=\])|[^\[\]\\`])*?')

link = Edit(r'^!?\[(label)\]\(\s*(href)(?:(?:[ \t]+(?:\n[ \t]*)?|\n[ \t]*)(title))?\s*\)').replace('label', _inlineLabel).replace('href', r'<(?:\\.|[^\n<>\\])+>|[^ \t\n\x00-\x1f]*').replace('title', r'"(?:\\"?|[^"\\])*"|\'(?:\\\'?|[^\'\\])*\'|\((?:\\\)?|[^)\\])*\)').getRegex()

reflink = Edit(r'^!?\[(label)\]\[(ref)\]').replace('label', _inlineLabel).replace('ref', _blockLabel).getRegex()
nolink = Edit(r'^!?\[(ref)\](?:\[\])?').replace('ref', _blockLabel).getRegex()

reflinkSearch = Edit(r'reflink|nolink(?!\()').replace('reflink', reflink).replace('nolink', nolink).getRegex()

_caseInsensitiveProtocol = re.compile(r'[hH][tT][tT][pP][sS]?|[fF][tT][pP]')

inlineNormal = {
    '_backpedal': noopTest,
    'anyPunctuation': anyPunctuation,
    'autolink': autolink,
    'blockSkip': blockSkip,
    'br': br_pat,
    'code': inlineCode,
    'del': noopTest,
    'delLDelim': noopTest,
    'delRDelim': noopTest,
    'emStrongLDelim': emStrongLDelim,
    'emStrongRDelimAst': emStrongRDelimAst,
    'emStrongRDelimUnd': emStrongRDelimUnd,
    'escape': escape,
    'link': link,
    'nolink': nolink,
    'punctuation': punctuation,
    'reflink': reflink,
    'reflinkSearch': reflinkSearch,
    'tag': tag,
    'text': inlineText,
    'url': noopTest
}

inlinePedantic = {
    **inlineNormal,
    'link': Edit(r'^!?\[(label)\]\((.*?)\)').replace('label', _inlineLabel).getRegex(),
    'reflink': Edit(r'^!?\[(label)\]\s*\[([^\]]*)\]').replace('label', _inlineLabel).getRegex()
}

inlineGfm = {
    **inlineNormal,
    'emStrongRDelimAst': emStrongRDelimAstGfm,
    'emStrongLDelim': emStrongLDelimGfm,
    'delLDelim': delLDelim,
    'delRDelim': delRDelim,
    'url': Edit(r'^((?:protocol):\/\/|www\.)(?:[a-zA-Z0-9\-]+\.?)+[^\s<]*|^email').replace('protocol', _caseInsensitiveProtocol).replace('email', r'[A-Za-z0-9._+-]+(@)[a-zA-Z0-9-_]+(?:\.[a-zA-Z0-9-_]*[a-zA-Z0-9])+(?![-_])').getRegex(),
    '_backpedal': re.compile(r'(?:[^?!.,:;*_\'"~()&]+|\([^)]*\)|&(?![a-zA-Z0-9]+;$)|[?!.,:;*_\'"~)]+(?!$))+'),
    'del': re.compile(r'^(~~?)(?=[^\s~])((?:\\[\s\S]|[^\\])*?(?:\\[\s\S]|[^\s~\\]))\1(?=[^~]|$)'),
    'text': Edit(r'^([`~]+|[^`~])(?:(?= {2,}\n)|(?=[a-zA-Z0-9.!#$%&\'*+\/=?_`{\|}~-]+@)|[\s\S]*?(?:(?=[\\<!\[`*~_]|\b_|protocol:\/\/|www\.|$)|[^ ](?= {2,}\n)|[^a-zA-Z0-9.!#$%&\'*+\/=?_`{\|}~-](?=[a-zA-Z0-9.!#$%&\'*+\/=?_`{\|}~-]+@)))').replace('protocol', _caseInsensitiveProtocol).getRegex()
}

inlineBreaks = {
    **inlineGfm,
    'br': Edit(br_pat).replace('{2,}', '*').getRegex(),
    'text': Edit(inlineGfm['text']).replace('\\b_', '\\b_| {2,}\\n').replace(r'\{2,\}', '*').getRegex()
}

block = {
    'normal': blockNormal,
    'gfm': blockGfm,
    'pedantic': blockPedantic
}

inline = {
    'normal': inlineNormal,
    'gfm': inlineGfm,
    'breaks': inlineBreaks,
    'pedantic': inlinePedantic
}

# ==========================================
# 3. Helper Functions
# ==========================================

ESCAPE_REPLACEMENTS = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
}

def get_escape_replacement(m):
    return ESCAPE_REPLACEMENTS[m.group(0)]

def escapeHtmlEntities(html, encode=False):
    if encode:
        if other['escapeTest'].search(html):
            return other['escapeReplace'].sub(get_escape_replacement, html)
    else:
        if other['escapeTestNoEncode'].search(html):
            return other['escapeReplaceNoEncode'].sub(get_escape_replacement, html)
    return html

def encodeURI(href):
    safe_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789;,/?:@&=+$-_.!~*'()#"
    return urllib.parse.quote(href, safe=safe_chars)

def cleanUrl(href):
    try:
        href = encodeURI(href).replace("%25", "%")
    except Exception:
        return None
    return href

def splitCells(tableRow, count=None):
    def pipe_replace(match):
        offset = match.start()
        full_str = match.string
        escaped = False
        curr = offset
        while True:
            curr -= 1
            if curr >= 0 and full_str[curr] == '\\':
                escaped = not escaped
            else:
                break
        if escaped:
            return '|'
        else:
            return ' |'

    row = other['findPipe'].sub(pipe_replace, tableRow)
    cells = row.split(' |')
    
    if cells and not cells[0].strip():
        cells.pop(0)
    if cells and not cells[-1].strip():
        cells.pop()
        
    if count is not None:
        if len(cells) > count:
            cells = cells[:count]
        else:
            while len(cells) < count:
                cells.append('')
                
    for i in range(len(cells)):
        cells[i] = other['slashPipe'].sub('|', cells[i].strip())
        
    return cells

def rtrim(s, c, invert=False):
    l = len(s)
    if l == 0:
        return ''
    suffLen = 0
    while suffLen < l:
        currChar = s[l - suffLen - 1]
        if currChar == c and not invert:
            suffLen += 1
        elif currChar != c and invert:
            suffLen += 1
        else:
            break
    return s[:l - suffLen]

def trimTrailingBlankLines(s):
    lines = s.split('\n')
    end = len(lines) - 1
    while end >= 0 and other['blankLine'].match(lines[end]):
        end -= 1
    if len(lines) - end <= 2:
        return s
    return '\n'.join(lines[:end + 1])

def findClosingBracket(s, b):
    if b[1] not in s:
        return -1
    level = 0
    i = 0
    n = len(s)
    while i < n:
        if s[i] == '\\':
            i += 1
        elif s[i] == b[0]:
            level += 1
        elif s[i] == b[1]:
            level -= 1
            if level < 0:
                return i
        i += 1
    if level > 0:
        return -2
    return -1

def expandTabs(line, indent=0):
    col = indent
    expanded = []
    for char in line:
        if char == '\t':
            added = 4 - (col % 4)
            expanded.append(' ' * added)
            col += added
        else:
            expanded.append(char)
            col += 1
    return "".join(expanded)

# ==========================================
# 4. Tokenizer Implementation
# ==========================================

def outputLink(cap, link, raw, lexer, rules):
    href = link['href']
    title = link['title'] if link['title'] else None
    text = rules['other']['outputLinkReplace'].sub('\\1', cap[1])
    
    lexer.state.inLink = True
    token = {
        'type': 'image' if cap[0].startswith('!') else 'link',
        'raw': raw,
        'href': href,
        'title': title,
        'text': text,
        'tokens': lexer.inlineTokens(text)
    }
    lexer.state.inLink = False
    return token

def indentCodeCompensation(raw, text, rules):
    matchIndentToCode = rules['other']['indentCodeCompensation'].search(raw)
    if not matchIndentToCode:
        return text
    indentToCode = matchIndentToCode.group(1)
    
    lines = text.split('\n')
    new_lines = []
    for node in lines:
        matchIndentInNode = rules['other']['beginningSpace'].match(node)
        if not matchIndentInNode:
            new_lines.append(node)
            continue
        indentInNode = matchIndentInNode.group(0)
        if len(indentInNode) >= len(indentToCode):
            new_lines.append(node[len(indentToCode):])
        else:
            new_lines.append(node)
    return '\n'.join(new_lines)

class Tokenizer:
    def __init__(self, options=None):
        self.options = options if options is not None else get_defaults()

    def space(self, src):
        cap = self.rules['block']['newline'].match(src)
        if cap and len(cap.group(0)) > 0:
            return {
                'type': 'space',
                'raw': cap.group(0)
            }

    def code(self, src):
        cap = self.rules['block']['code'].match(src)
        if cap:
            raw = cap.group(0) if self.options.get('pedantic') else trimTrailingBlankLines(cap.group(0))
            text = self.rules['other']['codeRemoveIndent'].sub('', raw)
            return {
                'type': 'code',
                'raw': raw,
                'codeBlockStyle': 'indented',
                'text': text
            }

    def fences(self, src):
        cap = self.rules['block']['fences'].match(src)
        if cap:
            raw = cap.group(0)
            cap3 = cap.group(3) if cap.group(3) is not None else ''
            text = indentCodeCompensation(raw, cap3, self.rules)
            
            lang = None
            cap2 = cap.group(2)
            if cap2 is not None:
                lang_trimmed = cap2.strip()
                lang = self.rules['inline']['anyPunctuation'].sub(r'\1', lang_trimmed)
            
            return {
                'type': 'code',
                'raw': raw,
                'lang': lang,
                'text': text
            }

    def heading(self, src):
        cap = self.rules['block']['heading'].match(src)
        if cap:
            text = cap.group(2).strip()
            if self.rules['other']['endingHash'].search(text):
                trimmed = rtrim(text, '#')
                if self.options.get('pedantic'):
                    text = trimmed.strip()
                elif not trimmed or self.rules['other']['endingSpaceChar'].search(trimmed):
                    text = trimmed.strip()
            return {
                'type': 'heading',
                'raw': rtrim(cap.group(0), '\n'),
                'depth': len(cap.group(1)),
                'text': text,
                'tokens': self.lexer.inline(text)
            }

    def hr(self, src):
        cap = self.rules['block']['hr'].match(src)
        if cap:
            return {
                'type': 'hr',
                'raw': rtrim(cap.group(0), '\n')
            }

    def blockquote(self, src):
        cap = self.rules['block']['blockquote'].match(src)
        if cap:
            lines = rtrim(cap.group(0), '\n').split('\n')
            raw = ''
            text = ''
            tokens = []
            
            while len(lines) > 0:
                inBlockquote = False
                currentLines = []
                
                i = 0
                while i < len(lines):
                    if self.rules['other']['blockquoteStart'].match(lines[i]):
                        currentLines.append(lines[i])
                        inBlockquote = True
                    elif not inBlockquote:
                        currentLines.append(lines[i])
                    else:
                        break
                    i += 1
                lines = lines[i:]
                
                currentRaw = '\n'.join(currentLines)
                currentText = self.rules['other']['blockquoteSetextReplace'].sub('\n    \\1', currentRaw)
                currentText = self.rules['other']['blockquoteSetextReplace2'].sub('', currentText)
                
                raw = f"{raw}\n{currentRaw}" if raw else currentRaw
                text = f"{text}\n{currentText}" if text else currentText
                
                top = self.lexer.state.top
                self.lexer.state.top = True
                self.lexer.blockTokens(currentText, tokens, True)
                self.lexer.state.top = top
                
                if len(lines) == 0:
                    break
                    
                lastToken = tokens[-1] if tokens else None
                if lastToken and lastToken['type'] == 'code':
                    break
                elif lastToken and lastToken['type'] == 'blockquote':
                    oldToken = lastToken
                    newText = oldToken['raw'] + '\n' + '\n'.join(lines)
                    newToken = self.blockquote(newText)
                    tokens[-1] = newToken
                    
                    raw = raw[:-len(oldToken['raw'])] + newToken['raw']
                    text = text[:-len(oldToken['text'])] + newToken['text']
                    break
                elif lastToken and lastToken['type'] == 'list':
                    oldToken = lastToken
                    newText = oldToken['raw'] + '\n' + '\n'.join(lines)
                    newToken = self.list(newText)
                    tokens[-1] = newToken
                    
                    raw = raw[:-len(lastToken['raw'])] + newToken['raw']
                    text = text[:-len(oldToken['raw'])] + newToken['raw']
                    lines = newText[len(tokens[-1]['raw']):].split('\n')
                    continue
                    
            return {
                'type': 'blockquote',
                'raw': raw,
                'tokens': tokens,
                'text': text
            }

    def list(self, src):
        cap = self.rules['block']['list'].match(src)
        if cap:
            bull = cap.group(1).strip()
            isordered = len(bull) > 1
            
            list_token = {
                'type': 'list',
                'raw': '',
                'ordered': isordered,
                'start': int(bull[:-1]) if isordered else '',
                'loose': False,
                'items': []
            }
            
            bull_escaped = f"\\d{{1,9}}\\{bull[-1]}" if isordered else f"\\{bull}"
            if self.options.get('pedantic'):
                bull_escaped = bull_escaped if isordered else '[*+-]'
                
            itemRegex = listItemRegex(bull_escaped)
            endsWithBlankLine = False
            
            while src:
                endEarly = False
                raw = ''
                itemContents = ''
                
                cap = itemRegex.match(src)
                if not cap:
                    break
                    
                if self.rules['block']['hr'].match(src):
                    break
                    
                raw = cap.group(0)
                src = src[len(raw):]
                
                line = expandTabs(cap.group(2).split('\n', 1)[0], len(cap.group(1)))
                nextLine = src.split('\n', 1)[0]
                blankLine = not line.strip()
                
                indent = 0
                if self.options.get('pedantic'):
                    indent = 2
                    itemContents = line.lstrip()
                elif blankLine:
                    indent = len(cap.group(1)) + 1
                else:
                    indent = len(line) - len(line.lstrip(' '))
                    indent = 1 if indent > 4 else indent
                    itemContents = line[indent:]
                    indent += len(cap.group(1))
                    
                if blankLine and self.rules['other']['blankLine'].match(nextLine):
                    raw += nextLine + '\n'
                    src = src[len(nextLine) + 1:]
                    endEarly = True
                    
                if not endEarly:
                    nextBulletRegex_pat = nextBulletRegex(indent)
                    hrRegex_pat = hrRegex(indent)
                    fencesBeginRegex_pat = fencesBeginRegex(indent)
                    headingBeginRegex_pat = headingBeginRegex(indent)
                    htmlBeginRegex_pat = htmlBeginRegex(indent)
                    blockquoteBeginRegex_pat = blockquoteBeginRegex(indent)
                    
                    while src:
                        rawLine = src.split('\n', 1)[0]
                        nextLine = rawLine
                        
                        if self.options.get('pedantic'):
                            nextLine = self.rules['other']['listReplaceNesting'].sub('  ', nextLine)
                            nextLineWithoutTabs = nextLine
                        else:
                            nextLineWithoutTabs = nextLine.replace('\t', '    ')
                            
                        if fencesBeginRegex_pat.match(nextLine):
                            break
                        if headingBeginRegex_pat.match(nextLine):
                            break
                        if htmlBeginRegex_pat.match(nextLine):
                            break
                        if blockquoteBeginRegex_pat.match(nextLine):
                            break
                        if nextBulletRegex_pat.match(nextLine):
                            break
                        if hrRegex_pat.match(nextLine):
                            break
                            
                        non_space_match = self.rules['other']['nonSpaceChar'].search(nextLineWithoutTabs)
                        first_non_space = non_space_match.start() if non_space_match else len(nextLineWithoutTabs)
                        
                        if first_non_space >= indent or not nextLine.strip():
                            itemContents += '\n' + nextLineWithoutTabs[indent:]
                        else:
                            if blankLine:
                                break
                            
                            line_without_tabs = line.replace('\t', '    ')
                            non_space_line_match = self.rules['other']['nonSpaceChar'].search(line_without_tabs)
                            line_first_non_space = non_space_line_match.start() if non_space_line_match else len(line_without_tabs)
                            
                            if line_first_non_space >= 4:
                                break
                            if fencesBeginRegex_pat.match(line):
                                break
                            if headingBeginRegex_pat.match(line):
                                break
                            if hrRegex_pat.match(line):
                                break
                                
                            itemContents += '\n' + nextLine
                            
                        blankLine = not nextLine.strip()
                        raw += rawLine + '\n'
                        src = src[len(rawLine) + 1:]
                        line = nextLineWithoutTabs[indent:]
                        
                if not list_token['loose']:
                    if endsWithBlankLine:
                        list_token['loose'] = True
                    elif self.rules['other']['doubleBlankLine'].search(raw):
                        endsWithBlankLine = True
                        
                list_token['items'].append({
                    'type': 'list_item',
                    'raw': raw,
                    'task': bool(self.options.get('gfm')) and bool(self.rules['other']['listIsTask'].match(itemContents)),
                    'loose': False,
                    'text': itemContents,
                    'tokens': []
                })
                list_token['raw'] += raw
                
            lastItem = list_token['items'][-1] if list_token['items'] else None
            if lastItem:
                lastItem['raw'] = lastItem['raw'].rstrip('\n')
                lastItem['text'] = lastItem['text'].rstrip('\n')
            else:
                return None
                
            list_token['raw'] = list_token['raw'].rstrip('\n')
            
            for item in list_token['items']:
                self.lexer.state.top = False
                item['tokens'] = self.lexer.blockTokens(item['text'], [])
                itemToken = item['tokens'][0] if item['tokens'] else None
                
                if item['task'] and itemToken and itemToken['type'] in ('text', 'paragraph'):
                    item['text'] = self.rules['other']['listReplaceTask'].sub('', item['text'])
                    itemToken['raw'] = self.rules['other']['listReplaceTask'].sub('', itemToken['raw'])
                    itemToken['text'] = self.rules['other']['listReplaceTask'].sub('', itemToken['text'])
                    
                    for i in range(len(self.lexer.inlineQueue) - 1, -1, -1):
                        if self.rules['other']['listIsTask'].match(self.lexer.inlineQueue[i]['src']):
                            self.lexer.inlineQueue[i]['src'] = self.rules['other']['listReplaceTask'].sub('', self.lexer.inlineQueue[i]['src'])
                            break
                            
                    taskRaw = self.rules['other']['listTaskCheckbox'].search(item['raw'])
                    if taskRaw:
                        checkboxToken = {
                            'type': 'checkbox',
                            'raw': taskRaw.group(0) + ' ',
                            'checked': taskRaw.group(0) != '[ ]'
                        }
                        item['checked'] = checkboxToken['checked']
                        if list_token['loose']:
                            if item['tokens'] and item['tokens'][0]['type'] in ('paragraph', 'text') and 'tokens' in item['tokens'][0] and item['tokens'][0]['tokens'] is not None:
                                item['tokens'][0]['raw'] = checkboxToken['raw'] + item['tokens'][0]['raw']
                                item['tokens'][0]['text'] = checkboxToken['raw'] + item['tokens'][0]['text']
                                item['tokens'][0]['tokens'].insert(0, checkboxToken)
                            else:
                                item['tokens'].insert(0, {
                                    'type': 'paragraph',
                                    'raw': checkboxToken['raw'],
                                    'text': checkboxToken['raw'],
                                    'tokens': [checkboxToken]
                                })
                        else:
                            item['tokens'].insert(0, checkboxToken)
                elif item['task']:
                    item['task'] = False
                    
                if not list_token['loose']:
                    spacers = [t for t in item['tokens'] if t['type'] == 'space']
                    hasMultipleLineBreaks = len(spacers) > 0 and any(self.rules['other']['anyLine'].search(t['raw']) for t in spacers)
                    list_token['loose'] = hasMultipleLineBreaks
                    
            if list_token['loose']:
                for item in list_token['items']:
                    item['loose'] = True
                    for token in item['tokens']:
                        if token['type'] == 'text':
                            token['type'] = 'paragraph'
                            
            return list_token

    def html(self, src):
        cap = self.rules['block']['html'].match(src)
        if cap:
            raw = trimTrailingBlankLines(cap.group(0))
            return {
                'type': 'html',
                'block': True,
                'raw': raw,
                'pre': cap.group(1) in ('pre', 'script', 'style'),
                'text': raw
            }

    def def_(self, src):
        cap = self.rules['block']['def'].match(src)
        if cap:
            tag = cap.group(1).lower()
            tag = self.rules['other']['multipleSpaceGlobal'].sub(' ', tag)
            
            href = ''
            cap2 = cap.group(2)
            if cap2:
                href = self.rules['other']['hrefBrackets'].sub('\\1', cap2)
                href = self.rules['inline']['anyPunctuation'].sub('\\1', href)
                
            title = cap.group(3)
            if title:
                title = title[1:-1]
                title = self.rules['inline']['anyPunctuation'].sub('\\1', title)
                
            return {
                'type': 'def',
                'tag': tag,
                'raw': rtrim(cap.group(0), '\n'),
                'href': href,
                'title': title
            }

    def table(self, src):
        cap = self.rules['block']['table'].match(src)
        if not cap:
            return None
            
        if not self.rules['other']['tableDelimiter'].search(cap.group(2)):
            return None
            
        headers = splitCells(cap.group(1))
        aligns_str = self.rules['other']['tableAlignChars'].sub('', cap.group(2))
        aligns = aligns_str.split('|')
        
        cap3 = cap.group(3)
        rows = []
        if cap3 and cap3.strip():
            rows = self.rules['other']['tableRowBlankLine'].sub('', cap3).split('\n')
            
        if len(headers) != len(aligns):
            return None
            
        item = {
            'type': 'table',
            'raw': rtrim(cap.group(0), '\n'),
            'header': [],
            'align': [],
            'rows': []
        }
        
        for align in aligns:
            if self.rules['other']['tableAlignRight'].match(align):
                item['align'].append('right')
            elif self.rules['other']['tableAlignCenter'].match(align):
                item['align'].append('center')
            elif self.rules['other']['tableAlignLeft'].match(align):
                item['align'].append('left')
            else:
                item['align'].append(None)
                
        for i in range(len(headers)):
            item['header'].append({
                'text': headers[i],
                'tokens': self.lexer.inline(headers[i]),
                'header': True,
                'align': item['align'][i]
            })
            
        for row in rows:
            cells = splitCells(row, len(item['header']))
            row_cells = []
            for i in range(len(cells)):
                row_cells.append({
                    'text': cells[i],
                    'tokens': self.lexer.inline(cells[i]),
                    'header': False,
                    'align': item['align'][i]
                })
            item['rows'].append(row_cells)
            
        return item

    def lheading(self, src):
        cap = self.rules['block']['lheading'].match(src)
        if cap:
            text = cap.group(1).strip()
            return {
                'type': 'heading',
                'raw': rtrim(cap.group(0), '\n'),
                'depth': 1 if cap.group(2)[0] == '=' else 2,
                'text': text,
                'tokens': self.lexer.inline(text)
            }

    def paragraph(self, src):
        cap = self.rules['block']['paragraph'].match(src)
        if cap:
            cap1 = cap.group(1)
            text = cap1[:-1] if cap1 and cap1[-1] == '\n' else cap1
            return {
                'type': 'paragraph',
                'raw': cap.group(0),
                'text': text,
                'tokens': self.lexer.inline(text)
            }

    def text(self, src):
        cap = self.rules['block']['text'].match(src)
        if cap:
            return {
                'type': 'text',
                'raw': cap.group(0),
                'text': cap.group(0),
                'tokens': self.lexer.inline(cap.group(0))
            }

    def escape(self, src):
        cap = self.rules['inline']['escape'].match(src)
        if cap:
            return {
                'type': 'escape',
                'raw': cap.group(0),
                'text': cap.group(1)
            }

    def tag(self, src):
        cap = self.rules['inline']['tag'].match(src)
        if cap:
            raw = cap.group(0)
            if not self.lexer.state.inLink and self.rules['other']['startATag'].match(raw):
                self.lexer.state.inLink = True
            elif self.lexer.state.inLink and self.rules['other']['endATag'].match(raw):
                self.lexer.state.inLink = False
                
            if not self.lexer.state.inRawBlock and self.rules['other']['startPreScriptTag'].match(raw):
                self.lexer.state.inRawBlock = True
            elif self.lexer.state.inRawBlock and self.rules['other']['endPreScriptTag'].match(raw):
                self.lexer.state.inRawBlock = False
                
            return {
                'type': 'html',
                'raw': raw,
                'inLink': self.lexer.state.inLink,
                'inRawBlock': self.lexer.state.inRawBlock,
                'block': False,
                'text': raw
            }

    def link(self, src):
        cap = self.rules['inline']['link'].match(src)
        if cap:
            trimmedUrl = cap.group(2).strip()
            if not self.options.get('pedantic') and self.rules['other']['startAngleBracket'].match(trimmedUrl):
                if not self.rules['other']['endAngleBracket'].match(trimmedUrl):
                    return None
                    
                rtrimSlash = rtrim(trimmedUrl[:-1], '\\')
                if (len(trimmedUrl) - len(rtrimSlash)) % 2 == 0:
                    return None
            else:
                lastParenIndex = findClosingBracket(cap.group(2), '()')
                if lastParenIndex == -2:
                    return None
                    
                if lastParenIndex > -1:
                    start = 5 if cap.group(0).startswith('!') else 4
                    linkLen = start + len(cap.group(1)) + lastParenIndex
                    cap0 = cap.group(0)[:linkLen].strip()
                    cap1 = cap.group(1)
                    cap2 = cap.group(2)[:lastParenIndex]
                    cap3 = ''
                    
                    href = cap2
                    title = ''
                    if self.options.get('pedantic'):
                        link_match = self.rules['other']['pedanticHrefTitle'].match(href)
                        if link_match:
                            href = link_match.group(1)
                            title = link_match.group(3)
                    else:
                        title = cap3
                        
                    href = href.strip()
                    if self.rules['other']['startAngleBracket'].match(href):
                        if self.options.get('pedantic') and not self.rules['other']['endAngleBracket'].match(trimmedUrl):
                            href = href[1:]
                        else:
                            href = href[1:-1]
                            
                    custom_cap = [cap0, cap1, cap2]
                    return outputLink(custom_cap, {
                        'href': self.rules['inline']['anyPunctuation'].sub('\\1', href) if href else href,
                        'title': self.rules['inline']['anyPunctuation'].sub('\\1', title) if title else title
                    }, cap0, self.lexer, self.rules)
                    
            href = cap.group(2)
            title = ''
            if self.options.get('pedantic'):
                link_match = self.rules['other']['pedanticHrefTitle'].match(href)
                if link_match:
                    href = link_match.group(1)
                    title = link_match.group(3)
            else:
                title = cap.group(3)[1:-1] if cap.group(3) else ''
                
            href = href.strip()
            if self.rules['other']['startAngleBracket'].match(href):
                if self.options.get('pedantic') and not self.rules['other']['endAngleBracket'].match(trimmedUrl):
                    href = href[1:]
                else:
                    href = href[1:-1]
                    
            custom_cap = [cap.group(0), cap.group(1), cap.group(2)]
            return outputLink(custom_cap, {
                'href': self.rules['inline']['anyPunctuation'].sub('\\1', href) if href else href,
                'title': self.rules['inline']['anyPunctuation'].sub('\\1', title) if title else title
            }, cap.group(0), self.lexer, self.rules)

    def reflink(self, src, links):
        cap = self.rules['inline']['reflink'].match(src)
        if not cap:
            cap = self.rules['inline']['nolink'].match(src)
            
        if cap:
            cap2 = cap.group(2) if len(cap.groups()) >= 2 else None
            linkString = cap2 if cap2 is not None else cap.group(1)
            linkString = self.rules['other']['multipleSpaceGlobal'].sub(' ', linkString)
            
            link = links.get(linkString.lower())
            if not link:
                text = cap.group(0)[0]
                return {
                    'type': 'text',
                    'raw': text,
                    'text': text
                }
                
            custom_cap = [cap.group(0), cap.group(1)]
            return outputLink(custom_cap, link, cap.group(0), self.lexer, self.rules)

    def emStrong(self, src, maskedSrc, prevChar=''):
        match = self.rules['inline']['emStrongLDelim'].match(src)
        if not match:
            return None
            
        g1 = match.group(1)
        g2 = match.group(2)
        g3 = match.group(3)
        g4 = match.group(4)
        if g1 is None and g2 is None and g3 is None and g4 is None:
            return None
            
        if g4 is not None and self.rules['other']['unicodeAlphaNumeric'].match(prevChar):
            return None
            
        nextChar = g1 if g1 is not None else (g3 if g3 is not None else '')
        
        if not nextChar or not prevChar or self.rules['inline']['punctuation'].match(prevChar):
            lLength = len(match.group(0)) - 1
            delimTotal = lLength
            midDelimTotal = 0
            
            is_ast = match.group(0)[0] == '*'
            endReg = self.rules['inline']['emStrongRDelimAst'] if is_ast else self.rules['inline']['emStrongRDelimUnd']
            
            masked_slice = maskedSrc[-len(src) + lLength:]
            
            for m in endReg.finditer(masked_slice):
                groups = m.groups()
                rDelim = None
                for g in groups:
                    if g is not None:
                        rDelim = g
                        break
                if not rDelim:
                    continue
                    
                rLength = len(rDelim)
                
                g3 = m.group(3) if len(groups) >= 3 else None
                g4 = m.group(4) if len(groups) >= 4 else None
                g5 = m.group(5) if len(groups) >= 5 else None
                g6 = m.group(6) if len(groups) >= 6 else None
                
                if g3 is not None or g4 is not None:
                    delimTotal += rLength
                    continue
                elif g5 is not None or g6 is not None:
                    if lLength % 3 and not ((lLength + rLength) % 3):
                        midDelimTotal += rLength
                        continue
                        
                  
                delimTotal -= rLength
                if delimTotal > 0:
                    continue
                    
                rLength = min(rLength, rLength + delimTotal + midDelimTotal)
                lastCharLength = len(m.group(0)[0])
                raw = src[:lLength + m.start() + lastCharLength + rLength]
                
                if min(lLength, rLength) % 2:
                    text = raw[1:-1]
                    return {
                        'type': 'em',
                        'raw': raw,
                        'text': text,
                        'tokens': self.lexer.inlineTokens(text)
                    }
                text = raw[2:-2]
                return {
                    'type': 'strong',
                    'raw': raw,
                    'text': text,
                    'tokens': self.lexer.inlineTokens(text)
                }

    def codespan(self, src):
        cap = self.rules['inline']['code'].match(src)
        if cap:
            text = self.rules['other']['newLineCharGlobal'].sub(' ', cap.group(2))
            hasNonSpaceChars = bool(self.rules['other']['nonSpaceChar'].search(text))
            hasSpaceCharsOnBothEnds = bool(self.rules['other']['startingSpaceChar'].match(text) and self.rules['other']['endingSpaceChar'].search(text))
            if hasNonSpaceChars and hasSpaceCharsOnBothEnds:
                text = text[1:-1]
            return {
                'type': 'codespan',
                'raw': cap.group(0),
                'text': text
            }

    def br(self, src):
        cap = self.rules['inline']['br'].match(src)
        if cap:
            return {
                'type': 'br',
                'raw': cap.group(0)
            }

    def del_(self, src, maskedSrc, prevChar=''):
        match = self.rules['inline']['delLDelim'].match(src)
        if not match:
            return None
            
        nextChar = match.group(1) if match.group(1) is not None else ''
        
        if not nextChar or not prevChar or self.rules['inline']['punctuation'].match(prevChar):
            lLength = len(match.group(0)) - 1
            delimTotal = lLength
            
            endReg = self.rules['inline']['delRDelim']
            masked_slice = maskedSrc[-len(src) + lLength:]
            
            for m in endReg.finditer(masked_slice):
                groups = m.groups()
                rDelim = None
                for g in groups:
                    if g is not None:
                        rDelim = g
                        break
                if not rDelim:
                    continue
                    
                rLength = len(rDelim)
                if rLength != lLength:
                    continue
                    
                if m.group(3) is not None or m.group(4) is not None:
                    delimTotal += rLength
                    continue
                    
                delimTotal -= rLength
                if delimTotal > 0:
                    continue
                    
                rLength = min(rLength, rLength + delimTotal)
                lastCharLength = len(m.group(0)[0])
                raw = src[:lLength + m.start() + lastCharLength + rLength]
                text = raw[lLength:-lLength]
                return {
                    'type': 'del',
                    'raw': raw,
                    'text': text,
                    'tokens': self.lexer.inlineTokens(text)
                }

    def autolink(self, src):
        cap = self.rules['inline']['autolink'].match(src)
        if cap:
            if cap.group(2) == '@':
                text = cap.group(1)
                href = 'mailto:' + text
            else:
                text = cap.group(1)
                href = text
            return {
                'type': 'link',
                'raw': cap.group(0),
                'text': text,
                'href': href,
                'tokens': [
                    {
                        'type': 'text',
                        'raw': text,
                        'text': text
                    }
                ]
            }

    def url(self, src):
        cap = self.rules['inline']['url'].match(src)
        if cap:
            if cap.group(2) == '@':
                text = cap.group(0)
                href = 'mailto:' + text
            else:
                cap0 = cap.group(0)
                prevCapZero = None
                while prevCapZero != cap0:
                    prevCapZero = cap0
                    backpedal_match = self.rules['inline']['_backpedal'].search(cap0)
                    cap0 = backpedal_match.group(0) if backpedal_match else ''
                text = cap0
                if cap.group(1) == 'www.':
                    href = 'http://' + cap0
                else:
                    href = cap0
            return {
                'type': 'link',
                'raw': text,
                'text': text,
                'href': href,
                'tokens': [
                    {
                        'type': 'text',
                        'raw': text,
                        'text': text
                    }
                ]
            }

    def inlineText(self, src):
        cap = self.rules['inline']['text'].match(src)
        if cap:
            escaped = self.lexer.state.inRawBlock
            return {
                'type': 'text',
                'raw': cap.group(0),
                'text': cap.group(0),
                'escaped': escaped
            }

# ==========================================
# 5. Lexer Implementation
# ==========================================

class TokensList(list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.links = {}

class LexerState:
    def __init__(self):
        self.inLink = False
        self.inRawBlock = False
        self.top = True

class Lexer:
    def __init__(self, options=None):
        self.tokens = TokensList()
        self.tokens.links = {}
        self.options = options if options is not None else get_defaults()
        
        if 'tokenizer' not in self.options or self.options['tokenizer'] is None:
            self.options['tokenizer'] = Tokenizer(self.options)
            
        self.tokenizer = self.options['tokenizer']
        self.tokenizer.options = self.options
        self.tokenizer.lexer = self
        self.inlineQueue = []
        self.state = LexerState()
        
        rules = {
            'other': other,
            'block': block['normal'],
            'inline': inline['normal']
        }
        
        if self.options.get('pedantic'):
            rules['block'] = block['pedantic']
            rules['inline'] = inline['pedantic']
        elif self.options.get('gfm'):
            rules['block'] = block['gfm']
            if self.options.get('breaks'):
                rules['inline'] = inline['breaks']
            else:
                rules['inline'] = inline['gfm']
                
        self.tokenizer.rules = rules

    @staticmethod
    def lex(src, options=None):
        lexer = Lexer(options)
        return lexer.lex_method(src)

    @staticmethod
    def lexInline(src, options=None):
        lexer = Lexer(options)
        return lexer.inlineTokens(src)

    def lex_method(self, src):
        src = re.sub(r'\r\n|\r', '\n', src)
        self.tokens = TokensList()
        self.tokens.links = {}
        
        self.blockTokens(src, self.tokens)
        
        for i in range(len(self.inlineQueue)):
            next_item = self.inlineQueue[i]
            self.inlineTokens(next_item['src'], next_item['tokens'])
            
        self.inlineQueue = []
        return self.tokens

    def blockTokens(self, src, tokens=None, lastParagraphClipped=False):
        if tokens is None:
            tokens = []
        self.tokenizer.lexer = self
        
        if self.options.get('pedantic'):
            src = src.replace('\t', '    ')
            src = self.rules['other']['spaceLine'].sub('', src)
            
        srcLength = float('inf')
        while src:
            if len(src) < srcLength:
                srcLength = len(src)
            else:
                self.infiniteLoopError(ord(src[0]))
                break
                
            token = None
            
            if self.options.get('extensions') and self.options['extensions'].get('block'):
                matched = False
                for extTokenizer in self.options['extensions']['block']:
                    token = extTokenizer(self, src, tokens)
                    if token:
                        src = src[len(token['raw']):]
                        tokens.append(token)
                        matched = True
                        break
                if matched:
                    continue
                    
            token = self.tokenizer.space(src)
            if token:
                src = src[len(token['raw']):]
                lastToken = tokens[-1] if tokens else None
                if len(token['raw']) == 1 and lastToken is not None:
                    lastToken['raw'] += '\n'
                else:
                    tokens.append(token)
                continue
                
            token = self.tokenizer.code(src)
            if token:
                src = src[len(token['raw']):]
                lastToken = tokens[-1] if tokens else None
                if lastToken and lastToken['type'] in ('paragraph', 'text'):
                    lastToken['raw'] += ('' if lastToken['raw'].endswith('\n') else '\n') + token['raw']
                    lastToken['text'] += '\n' + token['text']
                    self.inlineQueue[-1]['src'] = lastToken['text']
                else:
                    tokens.append(token)
                continue
                
            token = self.tokenizer.fences(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.heading(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.hr(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.blockquote(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.list(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.html(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.def_(src)
            if token:
                src = src[len(token['raw']):]
                lastToken = tokens[-1] if tokens else None
                if lastToken and lastToken['type'] in ('paragraph', 'text'):
                    lastToken['raw'] += ('' if lastToken['raw'].endswith('\n') else '\n') + token['raw']
                    lastToken['text'] += '\n' + token['raw']
                    self.inlineQueue[-1]['src'] = lastToken['text']
                elif token['tag'] not in self.tokens.links:
                    self.tokens.links[token['tag']] = {
                        'href': token['href'],
                        'title': token['title']
                    }
                    tokens.append(token)
                continue
                
            token = self.tokenizer.table(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.lheading(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            cutSrc = src
            if self.options.get('extensions') and self.options['extensions'].get('startBlock'):
                startIndex = float('inf')
                tempSrc = src[1:]
                for getStartIndex in self.options['extensions']['startBlock']:
                    tempStart = getStartIndex(self, tempSrc)
                    if isinstance(tempStart, (int, float)) and tempStart >= 0:
                        startIndex = min(startIndex, tempStart)
                if startIndex < float('inf') and startIndex >= 0:
                    cutSrc = src[:int(startIndex) + 1]
                    
            if self.state.top:
                token = self.tokenizer.paragraph(cutSrc)
                if token:
                    lastToken = tokens[-1] if tokens else None
                    if lastParagraphClipped and lastToken and lastToken['type'] == 'paragraph':
                        lastToken['raw'] += ('' if lastToken['raw'].endswith('\n') else '\n') + token['raw']
                        lastToken['text'] += '\n' + token['text']
                        self.inlineQueue.pop()
                        self.inlineQueue[-1]['src'] = lastToken['text']
                    else:
                        tokens.append(token)
                    lastParagraphClipped = len(cutSrc) != len(src)
                    src = src[len(token['raw']):]
                    continue
                    
            token = self.tokenizer.text(src)
            if token:
                src = src[len(token['raw']):]
                lastToken = tokens[-1] if tokens else None
                if lastToken and lastToken['type'] == 'text':
                    lastToken['raw'] += ('' if lastToken['raw'].endswith('\n') else '\n') + token['raw']
                    lastToken['text'] += '\n' + token['text']
                    self.inlineQueue.pop()
                    self.inlineQueue[-1]['src'] = lastToken['text']
                else:
                    tokens.append(token)
                continue
                
            if src:
                self.infiniteLoopError(ord(src[0]))
                break
                
        self.state.top = True
        return tokens

    def inline(self, src, tokens=None):
        if tokens is None:
            tokens = []
        self.inlineQueue.append({'src': src, 'tokens': tokens})
        return tokens

    def inlineTokens(self, src, tokens=None):
        if tokens is None:
            tokens = []
        self.tokenizer.lexer = self
        
        maskedSrc = src
        
        if self.tokens.links:
            links = list(self.tokens.links.keys())
            if len(links) > 0:
                reflinkSearch_pat = self.tokenizer.rules['inline']['reflinkSearch']
                lastIndex = 0
                while True:
                    match = reflinkSearch_pat.search(maskedSrc, lastIndex)
                    if not match:
                        break
                    
                    matched_str = match.group(0)
                    start_idx = match.start()
                    
                    bracket_idx = matched_str.rfind('[')
                    ref_key = matched_str[bracket_idx + 1:-1]
                    
                    if ref_key.lower() in links:
                        replacement = "[" + "a" * (len(matched_str) - 2) + "]"
                        maskedSrc = maskedSrc[:start_idx] + replacement + maskedSrc[match.end():]
                        lastIndex = start_idx + len(replacement)
                    else:
                        lastIndex = match.end()
                        
        anyPunctuation_pat = self.tokenizer.rules['inline']['anyPunctuation']
        maskedSrc = anyPunctuation_pat.sub('++', maskedSrc)
        
        blockSkip_pat = self.tokenizer.rules['inline']['blockSkip']
        lastIndex = 0
        while True:
            match = blockSkip_pat.search(maskedSrc, lastIndex)
            if not match:
                break
            g2 = match.group(2) if len(match.groups()) >= 2 else None
            offset = len(g2) if g2 is not None else 0
            
            start_idx = match.start()
            matched_len = len(match.group(0))
            
            replacement = "[" + "a" * (matched_len - offset - 2) + "]"
            maskedSrc = maskedSrc[:start_idx + offset] + replacement + maskedSrc[match.end():]
            lastIndex = start_idx + offset + len(replacement)
            
        if self.options.get('hooks') and hasattr(self.options['hooks'], 'emStrongMask'):
            maskedSrc = self.options['hooks'].emStrongMask(maskedSrc)
            
        keepPrevChar = False
        prevChar = ''
        srcLength = float('inf')
        
        while src:
            if len(src) < srcLength:
                srcLength = len(src)
            else:
                self.infiniteLoopError(ord(src[0]))
                break
                
            if not keepPrevChar:
                prevChar = ''
            keepPrevChar = False
            
            token = None
            
            if self.options.get('extensions') and self.options['extensions'].get('inline'):
                matched = False
                for extTokenizer in self.options['extensions']['inline']:
                    token = extTokenizer(self, src, tokens)
                    if token:
                        src = src[len(token['raw']):]
                        tokens.append(token)
                        matched = True
                        break
                if matched:
                    continue
                    
            token = self.tokenizer.escape(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.tag(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.link(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.reflink(src, self.tokens.links)
            if token:
                src = src[len(token['raw']):]
                lastToken = tokens[-1] if tokens else None
                if token['type'] == 'text' and lastToken and lastToken['type'] == 'text':
                    lastToken['raw'] += token['raw']
                    lastToken['text'] += token['text']
                else:
                    tokens.append(token)
                continue
                
            token = self.tokenizer.emStrong(src, maskedSrc, prevChar)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.codespan(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.br(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.del_(src, maskedSrc, prevChar)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            token = self.tokenizer.autolink(src)
            if token:
                src = src[len(token['raw']):]
                tokens.append(token)
                continue
                
            if not self.state.inLink:
                token = self.tokenizer.url(src)
                if token:
                    src = src[len(token['raw']):]
                    tokens.append(token)
                    continue
                    
            cutSrc = src
            if self.options.get('extensions') and self.options['extensions'].get('startInline'):
                startIndex = float('inf')
                tempSrc = src[1:]
                for getStartIndex in self.options['extensions']['startInline']:
                    tempStart = getStartIndex(self, tempSrc)
                    if isinstance(tempStart, (int, float)) and tempStart >= 0:
                        startIndex = min(startIndex, tempStart)
                if startIndex < float('inf') and startIndex >= 0:
                    cutSrc = src[:int(startIndex) + 1]
                    
            token = self.tokenizer.inlineText(cutSrc)
            if token:
                src = src[len(token['raw']):]
                if token['raw'][-1] != '_':
                    prevChar = token['raw'][-1]
                keepPrevChar = True
                lastToken = tokens[-1] if tokens else None
                if lastToken and lastToken['type'] == 'text':
                    lastToken['raw'] += token['raw']
                    lastToken['text'] += token['text']
                else:
                    tokens.append(token)
                continue
                
            if src:
                self.infiniteLoopError(ord(src[0]))
                break
                
        return tokens

    def infiniteLoopError(self, byte):
        errMsg = f"Infinite loop on byte: {byte}"
        if self.options.get('silent'):
            sys.stderr.write(errMsg + '\n')
        else:
            raise ValueError(errMsg)

# ==========================================
# 6. Renderer & Parser Implementation
# ==========================================

class Renderer:
    def __init__(self, options=None):
        self.options = options if options is not None else get_defaults()

    def space(self, token):
        return ''

    def code(self, token):
        text = token['text']
        lang = token.get('lang') or ''
        escaped = token.get('escaped')
        
        lang_match = other['notSpaceStart'].match(lang)
        langString = lang_match.group(0) if lang_match else ''
        
        code_str = (text[:-1] if text.endswith('\n') else text) + '\n'
        
        if not langString:
            return '<pre><code>' + (code_str if escaped else escapeHtmlEntities(code_str, True)) + '</code></pre>\n'
            
        return f'<pre><code class="language-{escapeHtmlEntities(langString)}">' + (code_str if escaped else escapeHtmlEntities(code_str, True)) + '</code></pre>\n'

    def blockquote(self, token):
        body = self.parser.parse(token['tokens'])
        return f"<blockquote>\n{body}</blockquote>\n"

    def html(self, token):
        return token['text']

    def def_rule(self, token):
        return ''

    def heading(self, token):
        return f"<h{token['depth']}>{self.parser.parseInline(token['tokens'])}</h{token['depth']}>\n"

    def hr(self, token):
        return '<hr>\n'

    def list(self, token):
        ordered = token['ordered']
        start = token['start']
        
        body = ''
        for item in token['items']:
            body += self.listitem(item)
            
        list_type = 'ol' if ordered else 'ul'
        startAttr = f' start="{start}"' if (ordered and start != 1) else ''
        return f'<{list_type}{startAttr}>\n{body}</{list_type}>\n'

    def listitem(self, item):
        return f"<li>{self.parser.parse(item['tokens'])}</li>\n"

    def checkbox(self, token):
        checked = token['checked']
        return '<input ' + ('checked="" ' if checked else '') + 'disabled="" type="checkbox"> '

    def paragraph(self, token):
        return f"<p>{self.parser.parseInline(token['tokens'])}</p>\n"

    def table(self, token):
        header_row = ''
        cell = ''
        for cell_token in token['header']:
            cell += self.tablecell(cell_token)
        header_row += self.tablerow({'text': cell})
        
        body = ''
        for row in token['rows']:
            cell = ''
            for cell_token in row:
                cell += self.tablecell(cell_token)
            body += self.tablerow({'text': cell})
            
        if body:
            body = f'<tbody>{body}</tbody>'
            
        return f"<table>\n<thead>\n{header_row}</thead>\n{body}</table>\n"

    def tablerow(self, token):
        return f"<tr>\n{token['text']}</tr>\n"

    def tablecell(self, token):
        content = self.parser.parseInline(token['tokens'])
        cell_type = 'th' if token['header'] else 'td'
        align = token.get('align')
        tag = f'<{cell_type} align="{align}">' if align else f'<{cell_type}>'
        return f"{tag}{content}</{cell_type}>\n"

    def strong(self, token):
        return f"<strong>{self.parser.parseInline(token['tokens'])}</strong>"

    def em(self, token):
        return f"<em>{self.parser.parseInline(token['tokens'])}</em>"

    def codespan(self, token):
        return f"<code>{escapeHtmlEntities(token['text'], True)}</code>"

    def br(self, token):
        return '<br>'

    def del_(self, token):
        return f"<del>{self.parser.parseInline(token['tokens'])}</del>"

    def link(self, token):
        text = self.parser.parseInline(token['tokens'])
        href = token['href']
        title = token.get('title')
        cleanHref = cleanUrl(href)
        if cleanHref is None:
            return text
        href = cleanHref
        out = f'<a href="{href}"'
        if title:
            out += f' title="{escapeHtmlEntities(title)}"'
        out += f'>{text}</a>'
        return out

    def image(self, token):
        text = token['text']
        if token.get('tokens'):
            text = self.parser.parseInline(token['tokens'], self.parser.textRenderer)
        href = token['href']
        title = token.get('title')
        cleanHref = cleanUrl(href)
        if cleanHref is None:
            return escapeHtmlEntities(text)
        href = cleanHref
        out = f'<img src="{href}" alt="{escapeHtmlEntities(text)}"'
        if title:
            out += f' title="{escapeHtmlEntities(title)}"'
        out += '>'
        return out

    def text(self, token):
        if 'tokens' in token and token['tokens'] is not None:
            return self.parser.parseInline(token['tokens'])
        return token['text'] if token.get('escaped') else escapeHtmlEntities(token['text'])

class TextRenderer:
    def strong(self, token):
        return token['text']

    def em(self, token):
        return token['text']

    def codespan(self, token):
        return token['text']

    def del_(self, token):
        return token['text']

    def html(self, token):
        return token['text']

    def text(self, token):
        return token['text']

    def link(self, token):
        return token['text']

    def image(self, token):
        return token['text']

    def br(self, token=None):
        return ''

    def checkbox(self, token):
        return token['raw']

class Parser:
    def __init__(self, options=None):
        self.options = options if options is not None else get_defaults()
        if 'renderer' not in self.options or self.options['renderer'] is None:
            self.options['renderer'] = Renderer(self.options)
        self.renderer = self.options['renderer']
        self.renderer.options = self.options
        self.renderer.parser = self
        self.textRenderer = TextRenderer()

    def parse(self, tokens=None):
        if not isinstance(self, Parser):
            # Static call: self is tokens, tokens is options
            parser = Parser(tokens)
            return parser.parse(self)
            
        # Instance call
        self.renderer.parser = self
        out = ''
        
        for token in tokens:
            if self.options.get('extensions') and self.options['extensions'].get('renderers') and token['type'] in self.options['extensions']['renderers']:
                ret = self.options['extensions']['renderers'][token['type']](self, token)
                if ret is not False:
                    out += ret or ''
                    continue
                    
            t_type = token['type']
            
            if t_type == 'escape':
                out += self.renderer.text(token)
            elif t_type == 'def':
                out += self.renderer.def_rule(token)
            elif t_type == 'del':
                out += self.renderer.del_(token)
            elif hasattr(self.renderer, t_type):
                out += getattr(self.renderer, t_type)(token)
            else:
                errMsg = f"Token with \"{t_type}\" type was not found."
                if self.options.get('silent'):
                    sys.stderr.write(errMsg + '\n')
                    return ''
                else:
                    raise ValueError(errMsg)
        return out

    def parseInline(self, tokens=None, renderer=None):
        if not isinstance(self, Parser):
            # Static call: self is tokens, tokens is options
            parser = Parser(renderer)
            return parser.parseInline(self)
            
        # Instance call
        if renderer is None:
            renderer = self.renderer
        self.renderer.parser = self
        out = ''
        
        for token in tokens:
            if self.options.get('extensions') and self.options['extensions'].get('renderers') and token['type'] in self.options['extensions']['renderers']:
                ret = self.options['extensions']['renderers'][token['type']](self, token)
                if ret is not False:
                    out += ret or ''
                    continue
                    
            t_type = token['type']
            
            if t_type == 'escape':
                out += renderer.text(token)
            elif t_type == 'def':
                out += renderer.def_rule(token)
            elif t_type == 'del':
                out += renderer.del_(token)
            elif hasattr(renderer, t_type):
                out += getattr(renderer, t_type)(token)
            else:
                errMsg = f"Token with \"{t_type}\" type was not found."

                if self.options.get('silent'):
                    sys.stderr.write(errMsg + '\n')
                    return ''
                else:
                    raise ValueError(errMsg)
        return out


# ==========================================
# 7. Marked Core Class
# ==========================================

def get_defaults():
    return {
        'async': False,
        'breaks': False,
        'extensions': None,
        'gfm': True,
        'hooks': None,
        'pedantic': False,
        'renderer': None,
        'silent': False,
        'tokenizer': None,
        'walkTokens': None,
    }

class Marked:
    def __init__(self, *args):
        self.defaults = get_defaults()
        self.use(*args)

    def setOptions(self, opt):
        self.defaults.update(opt)
        return self

    def use(self, *args):
        for pack in args:
            if not pack:
                continue
            self.defaults.update(pack)
        return self

    def lex(self, src, options=None):
        return Lexer.lex(src, options or self.defaults)

    def parse(self, src, options=None):
        opt = dict(self.defaults)
        if options:
            opt.update(options)
            
        if opt.get('hooks') and hasattr(opt['hooks'], 'preprocess'):
            src = opt['hooks'].preprocess(src)
            
        lexer = Lexer(opt)
        tokens = lexer.lex_method(src)
        
        if opt.get('hooks') and hasattr(opt['hooks'], 'processAllTokens'):
            tokens = opt['hooks'].processAllTokens(tokens)
            
        if opt.get('walkTokens'):
            self.walkTokens(tokens, opt['walkTokens'])
            
        parser = Parser(opt)
        html = parser.parse(tokens)
        
        if opt.get('hooks') and hasattr(opt['hooks'], 'postprocess'):
            html = opt['hooks'].postprocess(html)
            
        return html

    def parseInline(self, src, options=None):
        opt = dict(self.defaults)
        if options:
            opt.update(options)
            
        lexer = Lexer(opt)
        tokens = lexer.inlineTokens(src)
        parser = Parser(opt)
        return parser.parseInline(tokens)


    def walkTokens(self, tokens, callback):
        for token in tokens:
            callback(token)
            t_type = token['type']
            if t_type == 'table':
                for cell in token['header']:
                    self.walkTokens(cell['tokens'], callback)
                for row in token['rows']:
                    for cell in row:
                        self.walkTokens(cell['tokens'], callback)
            elif t_type == 'list':
                self.walkTokens(token['items'], callback)
            elif 'tokens' in token and token['tokens'] is not None:
                self.walkTokens(token['tokens'], callback)

# ==========================================
# 8. CLI Entry Main Logic
# ==========================================

def main():
    argv = sys.argv[1:]
    
    files = []
    options = {}
    input_val = None
    output_val = None
    string_val = None
    tokens = False
    config = None
    noclobber = False
    
    def getArg():
        nonlocal argv
        if not argv:
            return None
        arg = argv.pop(0)
        if arg.startswith('--'):
            parts = arg.split('=', 1)
            if len(parts) > 1:
                argv.insert(0, parts[1])
                arg = parts[0]
        elif arg.startswith('-') and len(arg) > 1:
            if len(arg) > 2:
                expanded = ['-' + ch for ch in arg[1:]]
                argv = expanded + argv
                arg = argv.pop(0)
        return arg

    marked_inst = Marked()
    defaults = marked_inst.defaults

    while argv:
        arg = getArg()
        if arg is None:
            break
        if arg in ('-o', '--output'):
            output_val = argv.pop(0) if argv else None
        elif arg in ('-i', '--input'):
            input_val = argv.pop(0) if argv else None
        elif arg in ('-s', '--string'):
            string_val = argv.pop(0) if argv else None
        elif arg in ('-t', '--tokens'):
            tokens = True
        elif arg in ('-c', '--config'):
            config = argv.pop(0) if argv else None
        elif arg in ('-n', '--no-clobber'):
            noclobber = True
        elif arg in ('-h', '--help'):
            here = os.path.dirname(os.path.abspath(__file__))
            man_path = os.path.abspath(os.path.join(here, "..", "source", "man", "marked.1.md"))
            if os.path.exists(man_path):
                with open(man_path, 'r', encoding='utf-8') as f:
                    sys.stdout.write(f.read())
            else:
                sys.stdout.write("Marked Markdown Parser CLI Help\n")
            sys.exit(0)
        elif arg in ('-v', '--version'):
            here = os.path.dirname(os.path.abspath(__file__))
            pkg_path = os.path.abspath(os.path.join(here, "..", "source", "package.json"))
            if os.path.exists(pkg_path):
                with open(pkg_path, 'r', encoding='utf-8') as f:
                    pkg = json.load(f)
                    sys.stdout.write(pkg.get('version', '') + '\n')
            else:
                sys.stdout.write("18.0.5\n")
            sys.exit(0)
        else:
            if arg.startswith('--'):
                opt_name = arg.replace('--no-', '').replace('--', '')
                opt_name = re.sub(r'-(\w)', lambda m: m.group(1).upper(), opt_name)
                
                if opt_name not in defaults:
                    continue
                    
                default_val = defaults[opt_name]
                if arg.startswith('--no-'):
                    options[opt_name] = False if isinstance(default_val, bool) else None
                else:
                    if isinstance(default_val, bool):
                        options[opt_name] = True
                    else:
                        options[opt_name] = argv.pop(0) if argv else None
            else:
                files.append(arg)

    def getData():
        if string_val is not None:
            return string_val
        if input_val is not None:
            with open(input_val, 'r', encoding='utf-8') as f:
                return f.read()
        if files:
            with open(files[-1], 'r', encoding='utf-8') as f:
                return f.read()
        return sys.stdin.read()

    data = getData()

    def resolve_config(config_path):
        p = os.path.abspath(os.path.expanduser(config_path))
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                content = f.read()
            try:
                cfg = json.loads(content)
                marked_inst.use(cfg)
                return
            except Exception:
                pass
                
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1 and end > start:
                try:
                    obj_str = content[start:end+1]
                    obj_str = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)', r'\1"\2"\3', obj_str)
                    obj_str = obj_str.replace("'", '"')
                    cfg = json.loads(obj_str)
                    marked_inst.use(cfg)
                    return
                except Exception:
                    pass

            cfg = {}
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('//') or line.startswith('/*') or line.endswith('*/'):
                    continue
                match = re.search(r'([a-zA-Z_][a-zA-Z0-9_]*)\s*[:=]\s*(true|false|null|\d+|"[^"]*"|\'[^\']*\')', line)
                if match:
                    key = match.group(1)
                    val_str = match.group(2)
                    if val_str == 'true':
                        val = True
                    elif val_str == 'false':
                        val = False
                    elif val_str == 'null':
                        val = None
                    elif val_str.isdigit():
                        val = int(val_str)
                    else:
                        val = val_str[1:-1]
                    cfg[key] = val
            if cfg:
                marked_inst.use(cfg)

    if config:
        resolve_config(config)
    else:
        for default_cfg in ('~/.marked.json', '~/.marked.js', '~/.marked/index.js'):
            p = os.path.abspath(os.path.expanduser(default_cfg))
            if os.path.exists(p):
                resolve_config(p)
                break

    marked_inst.setOptions(options)
    if tokens:
        tokens_list = marked_inst.lex(data)
        
        def clean_token(t):
            if isinstance(t, list):
                return [clean_token(item) for item in t]
            if isinstance(t, dict):
                cleaned = {}
                for k, v in t.items():
                    if v is not None:
                        cleaned[k] = clean_token(v)
                return cleaned
            return t

        sys.stdout.write(json.dumps(clean_token(tokens_list), indent=2) + '\n')
    else:
        html = marked_inst.parse(data)
        if output_val:
            if noclobber and os.path.exists(output_val):
                sys.stderr.write(f"marked: output file '{output_val}' already exists, disable the '-n' / '--no-clobber' flag to overwrite\n")
                sys.exit(1)
            with open(output_val, 'w', encoding='utf-8') as f:
                f.write(html)
        else:
            sys.stdout.write(html + '\n')

if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except FileNotFoundError as err:
        sys.stderr.write(f"marked: {err.filename}: No such file or directory\n")
        sys.exit(1)
    except Exception as err:
        sys.stderr.write(str(err) + '\n')
        sys.exit(1)
