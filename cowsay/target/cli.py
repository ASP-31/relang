#!/usr/bin/env python3
import argparse
import sys
import os
import cowsay

def main():
    # Detect if we should think based on script invocation name
    script_name = os.path.basename(sys.argv[0]).lower()
    default_think = "cowthink" in script_name
    
    parser = argparse.ArgumentParser(
        usage="Usage: %(prog)s [-e eye_string] [-f cowfile] [-h] [-l] [-n] [-T tongue_string] [-W column] [-bdgpstwy] text",
        add_help=False
    )
    
    parser.add_argument('-e', default='oo')
    parser.add_argument('-T', default='  ')
    parser.add_argument('-W', default=40, type=int)
    parser.add_argument('-f', default='default')
    parser.add_argument('--think', action='store_true', default=default_think)
    
    # Mode flags
    parser.add_argument('-b', action='store_true')
    parser.add_argument('-d', action='store_true')
    parser.add_argument('-g', action='store_true')
    parser.add_argument('-p', action='store_true')
    parser.add_argument('-s', action='store_true')
    parser.add_argument('-t', action='store_true')
    parser.add_argument('-w', action='store_true')
    parser.add_argument('-y', action='store_true')
    
    # Other flags
    parser.add_argument('-n', action='store_true')
    parser.add_argument('-r', action='store_true')
    parser.add_argument('-l', action='store_true')
    parser.add_argument('-h', '--help', action='store_true')
    
    # Message (positional arguments)
    parser.add_argument('message', nargs='*', default=[])
    
    args, unknown = parser.parse_known_args()
    
    if args.help:
        print_help()
        sys.exit(0)
        
    if args.l:
        cows_list = cowsay.list_cows()
        print("  ".join(cows_list))
        sys.exit(0)
        
    options = vars(args)
    
    if args.message:
        text = " ".join(args.message)
        options['text'] = text
        run_cowsay(options)
    else:
        # Read from stdin
        try:
            data = sys.stdin.read()
        except KeyboardInterrupt:
            sys.exit(130)
            
        if data:
            if data.endswith('\n'):
                data = data[:-1]
            if data.endswith('\r'):
                data = data[:-1]
            options['text'] = data
            run_cowsay(options)
        else:
            print_help()
            sys.exit(0)

def print_help():
    help_text = """
Usage: cowsay [-e eye_string] [-f cowfile] [-h] [-l] [-n] [-T tongue_string] [-W column] [-bdgpstwy] text

If any command-line arguments are left over after all switches have been processed, they become the cow's message.

If the program is invoked as cowthink then the cow will think its message instead of saying it.

Options:
  -e          Select the appearance of the cow's eyes.                  [default: "oo"]
  -T          The tongue is configurable similarly to the eyes through -T and tongue_string. [default: "  "]
  -W          Specifies roughly where the message should be wrapped. The default is equivalent to -W 40 i.e. wrap words at or before the 40th column. [default: 40]
  -f          Specifies a cow picture file ('cowfile') to use. It can be either a path to a cow file or the name of one of cows included in the package. [default: "default"]
  --think     Think the message instead of saying it aloud.             [boolean]
  -b          Mode: Borg                                                [boolean]
  -d          Mode: Dead                                                [boolean]
  -g          Mode: Greedy                                              [boolean]
  -p          Mode: Paranoia                                            [boolean]
  -s          Mode: Stoned                                              [boolean]
  -t          Mode: Tired                                               [boolean]
  -w          Mode: Wired                                               [boolean]
  -y          Mode: Youthful                                            [boolean]
  -n          If it is specified, the given message will not be word-wrapped. [boolean]
  -r          Select a random cow                                       [boolean]
  -l          List all cowfiles included in this package.                [boolean]
  -h, --help  Display this help message                                 [boolean]
"""
    print(help_text.strip())

def run_cowsay(options):
    say_aloud = not options.get('think')
    print(cowsay.do_it(options, say_aloud))

if __name__ == '__main__':
    main()
