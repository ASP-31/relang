import os
import re
import random
import sys
import unicodedata

# Determine target directory paths
COWS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cows")

# Cache for read cow files
text_cache = {}

# Regex to strip ANSI escape sequences
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b[@-Z\\-_]')

def strip_ansi(s):
    return ANSI_ESCAPE.sub('', s)

def string_width(s):
    s_clean = strip_ansi(s)
    width = 0
    for char in s_clean:
        code = ord(char)
        if code < 32 or (127 <= code < 160):
            continue
        try:
            eaw = unicodedata.east_asian_width(char)
            if eaw in ('F', 'W'):
                width += 2
            else:
                width += 1
        except Exception:
            width += 1
    return width

def split_text(text, wrap):
    # Normalize newlines
    text = re.sub(r'\r\n?|[\n\u2028\u2029]', '\n', text)
    if text.startswith('\uFEFF'):
        text = text[1:]
    # Replace tabs with 8 spaces
    text = text.replace('\t', '        ')
    
    if not wrap:
        return text.split('\n')
        
    lines = []
    start = 0
    text_len = len(text)
    while start < text_len:
        next_new_line = text.find('\n', start)
        if next_new_line == -1:
            next_new_line = text_len
            
        wrap_at = min(start + wrap, next_new_line)
        lines.append(text[start:wrap_at])
        start = wrap_at
        
        if start < text_len and text[start] == '\n':
            start += 1
            
    return lines

def pad(text, length):
    return text + " " * (length - string_width(text))

def top(length):
    return "_" * (length + 2)

def bottom(length):
    return "-" * (length + 2)

def format_balloon(text, wrap, delimiters):
    lines = split_text(text, wrap)
    if not lines:
        max_len = 0
    else:
        max_len = max(string_width(line) for line in lines)
        
    balloon = []
    if len(lines) == 1:
        balloon.append(" " + top(max_len))
        balloon.append(f"{delimiters['only'][0]} {lines[0]} {delimiters['only'][1]}")
        balloon.append(" " + bottom(max_len))
    else:
        balloon.append(" " + top(max_len))
        for i, line in enumerate(lines):
            if i == 0:
                delim = delimiters['first']
            elif i == len(lines) - 1:
                delim = delimiters['last']
            else:
                delim = delimiters['middle']
            balloon.append(f"{delim[0]} {pad(line, max_len)} {delim[1]}")
        balloon.append(" " + bottom(max_len))
        
    return "\n".join(balloon)

def say_balloon(text, wrap=None):
    delimiters = {
        "first": ["/", "\\"],
        "middle": ["|", "|"],
        "last": ["\\", "/"],
        "only": ["<", ">"]
    }
    return format_balloon(text, wrap, delimiters)

def think_balloon(text, wrap=None):
    delimiters = {
        "first": ["(", ")"],
        "middle": ["(", ")"],
        "last": ["(", ")"],
        "only": ["(", ")"]
    }
    return format_balloon(text, wrap, delimiters)

MODES = {
    "b": {"eyes": "==", "tongue": "  "},
    "d": {"eyes": "xx", "tongue": "U "},
    "g": {"eyes": "$$", "tongue": "  "},
    "p": {"eyes": "@@", "tongue": "  "},
    "s": {"eyes": "**", "tongue": "U "},
    "t": {"eyes": "--", "tongue": "  "},
    "w": {"eyes": "OO", "tongue": "  "},
    "y": {"eyes": "..", "tongue": "  "}
}

def get_face(options):
    for mode in ["b", "d", "g", "p", "s", "t", "w", "y"]:
        if options.get(mode):
            return dict(MODES[mode])
    return {
        "eyes": options.get("e") or "oo",
        "tongue": options.get("T") or "  "
    }

def extract_the_cow(cow):
    cow = re.sub(r'\r\n?|[\n\u2028\u2029]', '\n', cow)
    if cow.startswith('\uFEFF'):
        cow = cow[1:]
        
    match = re.search(r'\$the_cow\s*=\s*<<"*EOC"*;*\n([\s\S]+?)\nEOC(?:\n|$)', cow)
    if not match:
        print("Cannot parse cow file\n", cow, file=sys.stderr)
        return cow
        
    body = match.group(1)
    body = body.replace('\\\\', '\\').replace('\\@', '@').replace('\\$', '$')
    return body

def replace_cow_vars(cow_text, variables):
    eyes = variables.get('eyes', 'oo')
    eyeL = eyes[0] if len(eyes) > 0 else ""
    eyeR = eyes[1] if len(eyes) > 1 else ""
    tongue = variables.get('tongue', '  ')
    thoughts = variables.get('thoughts', '\\')
    
    if "$the_cow" in cow_text:
        cow_text = extract_the_cow(cow_text)
        
    cow_text = cow_text.replace("$thoughts", thoughts)
    cow_text = cow_text.replace("${eyes}", eyes)
    cow_text = cow_text.replace("$eyes", eyes)
    cow_text = cow_text.replace("${tongue}", tongue)
    cow_text = cow_text.replace("$tongue", tongue)
    cow_text = cow_text.replace("$eye", eyeL, 1)
    cow_text = cow_text.replace("$eye", eyeR, 1)
    
    return cow_text

def get_cow(cow):
    if cow in text_cache:
        text = text_cache[cow]
    else:
        if "\\" in cow or "/" in cow:
            file_path = cow
        else:
            file_path = os.path.join(COWS_DIR, cow + ".cow")
            
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        text_cache[cow] = text
        
    return lambda options: replace_cow_vars(text, options)

def list_cows():
    if not os.path.exists(COWS_DIR):
        return []
    files = os.listdir(COWS_DIR)
    cow_names = []
    for f in files:
        if f.endswith(".cow"):
            cow_names.append(f[:-4])
    return sorted(cow_names, key=str.lower)

def do_it(options, say_aloud):
    if options.get("r"):
        cows_list = list_cows()
        cow_file = random.choice(cows_list) if cows_list else "default"
    else:
        cow_file = options.get("f") or "default"
        
    cow_func = get_cow(cow_file)
    face = get_face(options)
    face["thoughts"] = "\\" if say_aloud else "o"
    
    text = options.get("text") or ""
    wrap = None if options.get("n") else options.get("W", 40)
    
    balloon_func = say_balloon if say_aloud else think_balloon
    return balloon_func(text, wrap) + "\n" + cow_func(face)

def say(text=None, **kwargs):
    if text is not None:
        kwargs['text'] = text
    return do_it(kwargs, say_aloud=True)

def think(text=None, **kwargs):
    if text is not None:
        kwargs['text'] = text
    return do_it(kwargs, say_aloud=False)
