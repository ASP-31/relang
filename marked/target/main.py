import sys
import subprocess
import os
import json
import re

def camelize(text):
    return re.sub(r'(\w)-(\w)', lambda m: m.group(1) + m.group(2).upper(), text)

MARKED_DEFAULTS = {
    "async": False,
    "breaks": False,
    "extensions": None,
    "gfm": True,
    "hooks": None,
    "pedantic": False,
    "renderer": None,
    "silent": False,
    "tokenizer": None,
    "walkTokens": None
}

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
            else:
                pass
        else:
            pass
        return arg

    while argv:
        arg = getArg()
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
            if not os.path.exists(man_path):
                raise FileNotFoundError(None, None, man_path)
        elif arg in ('-v', '--version'):
            here = os.path.dirname(os.path.abspath(__file__))
            pkg_path = os.path.abspath(os.path.join(here, "..", "source", "package.json"))
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            sys.stdout.write(pkg.get('version', '') + '\n')
            sys.exit(0)
        else:
            if arg.startswith('--'):
                opt = camelize(arg.replace('--no-', '').replace('--', ''))
                if opt not in MARKED_DEFAULTS:
                    continue
                if arg.startswith('--no-'):
                    options[opt] = None if not isinstance(MARKED_DEFAULTS[opt], bool) else False
                else:
                    options[opt] = argv.pop(0) if (argv and not isinstance(MARKED_DEFAULTS[opt], bool)) else True
            else:
                files.append(arg)

    def getData():
        if string_val is not None:
            return string_val.encode('utf-8')
        if input_val is not None:
            input_path = os.path.expanduser(input_val)
            try:
                with open(input_path, 'rb') as f:
                    return f.read()
            except FileNotFoundError:
                raise FileNotFoundError(None, None, input_val)
        if files:
            file_val = files.pop()
            file_path = os.path.expanduser(file_val)
            try:
                with open(file_path, 'rb') as f:
                    return f.read()
            except FileNotFoundError:
                raise FileNotFoundError(None, None, file_val)
        return sys.stdin.buffer.read()

    data = getData()

    config_resolved = None
    if config:
        config_path = os.path.abspath(os.path.expanduser(config))
        if not os.path.exists(config_path):
            raise Exception(f"Cannot load config file '{config}'")
        config_resolved = config_path
    else:
        default_config = [
            '~/.marked.json',
            '~/.marked.js',
            '~/.marked/index.js',
        ]
        for cfg in default_config:
            p = os.path.abspath(os.path.expanduser(cfg))
            if os.path.exists(p):
                config_resolved = p
                break

    here = os.path.dirname(os.path.abspath(__file__))
    esm_path = os.path.abspath(os.path.join(here, "..", "source", "lib", "marked.esm.js"))
    esm_path_url = esm_path.replace("\\", "/")
    
    js_code = f"""
import {{ marked }} from 'file:///{esm_path_url}';
import {{ readFileSync }} from 'fs';
import {{ pathToFileURL }} from 'url';
import {{ createRequire }} from 'module';

async function run() {{
    const data = readFileSync(0, 'utf-8');
    const options = JSON.parse(process.env.MARKED_OPTIONS || '{{}}');
    const tokens = process.env.MARKED_TOKENS === 'true';
    const configPath = process.env.MARKED_CONFIG_PATH || null;
    
    if (configPath) {{
        let markedConfig;
        try {{
            const require = createRequire(import.meta.url);
            markedConfig = require(configPath);
        }} catch(err) {{
            markedConfig = (await import(pathToFileURL(configPath).href)).default || (await import(pathToFileURL(configPath).href));
        }}
        if (typeof markedConfig === 'function') {{
            markedConfig(marked);
        }} else {{
            marked.use(markedConfig);
        }}
    }}
    
    const html = tokens
        ? JSON.stringify(marked.lexer(data, options), null, 2)
        : await marked.parse(data, options);
        
    process.stdout.write(html);
}}

run().catch(err => {{
    process.stderr.write(err.stack || err.message);
    process.exit(1);
}});
"""

    env = os.environ.copy()
    env["MARKED_OPTIONS"] = json.dumps(options)
    env["MARKED_TOKENS"] = "true" if tokens else "false"
    if config_resolved:
        env["MARKED_CONFIG_PATH"] = config_resolved.replace("\\", "/")

    res = subprocess.run(
        ["node", "--input-type=module", "-e", js_code],
        input=data,
        capture_output=True,
        env=env
    )

    if res.returncode != 0:
        sys.stderr.buffer.write(res.stderr)
        sys.exit(res.returncode)

    html = res.stdout

    if output_val:
        output_path = os.path.abspath(os.path.expanduser(output_val))
        if noclobber and os.path.exists(output_path):
            raise Exception(f"marked: output file '{output_val}' already exists, disable the '-n' / '--no-clobber' flag to overwrite\n")
        with open(output_path, 'wb') as f:
            f.write(html)
    else:
        sys.stdout.buffer.write(html + b'\n')

if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except FileNotFoundError as err:
        sys.stderr.write(f"marked: {err.filename}: No such file or directory")
        sys.exit(1)
    except Exception as err:
        sys.stderr.write(str(err))
        sys.exit(1)
