#!/usr/bin/env python3
import sys
import os
import getopt
import re
from PIL import Image

# Match flag bitwise values from args.h
GRAYSCALE_FLAG = 1 << 0
REVERSE_FLAG   = 1 << 1
PRINT_FLAG     = 1 << 2
DEBUG_FLAG     = 1 << 3

def atoi(s):
    match = re.match(r'^\s*([+-]?\d+)', s)
    if match:
        return int(match.group(1))
    return 0


def show_usage():
    # Keep output formatting identical to utils.h show_usage()
    sys.stdout.write(
        "\nUsage: \x1b[1mimg2ascii [options] -i <FILE> [-o <FILE>]\x1b[0m \n\n"
        "A command-line tool for converting images to ASCII art \n\n"
        "Options: \n"
        "   -i, --input  <FILE>     Path of the input image file (required) \n"
        "   -o, --output <FILE>     Path of the output file \n"
        "   -w, --width  <NUMBER>   Width of the output \n"
        "   -c, --chars  <STRING>   Characters to be used for the ASCII image \n"
        "   -p, --print             Print the output to the console \n"
        "   -r, --reverse           Reverse the string of characters \n"
        "   -d, --debug             Print some useful information \n\n"
    )

def get_intensity(r, g, b):
    # relative luminance formula, using rounding that matches C's round() for positive numbers
    return int(0.299 * r + 0.587 * g + 0.114 * b + 0.5)

def get_output_grayscale(pixels, desired_width, desired_height, characters):
    characters_count = len(characters)
    output = []
    
    for i in range(desired_height * desired_width):
        r, g, b = pixels[i]
        intensity = get_intensity(r, g, b)
        
        char_index = int(intensity / (255.0 / (characters_count - 1)))
        char_index = max(0, min(char_index, characters_count - 1))
        
        output.append(characters[char_index])
        
        if (i + 1) % desired_width == 0:
            output.append('\n')
            
    return "".join(output)

def get_output_rgb(pixels, desired_width, desired_height, characters):
    characters_count = len(characters)
    output = []
    
    # Initialize prev variables to values that won't match any RGB color
    # to guarantee that the first pixel prints its ANSI sequence.
    r_prev, g_prev, b_prev = None, None, None
    
    for i in range(desired_height * desired_width):
        r, g, b = pixels[i]
        intensity = get_intensity(r, g, b)
        
        char_index = int(intensity / (255.0 / (characters_count - 1)))
        char_index = max(0, min(char_index, characters_count - 1))
        
        if not (r == r_prev and g == g_prev and b == b_prev):
            output.append(f"\x1b[38;2;{r};{g};{b}m")
            
        r_prev, g_prev, b_prev = r, g, b
        
        output.append(characters[char_index])
        
        if (i + 1) % desired_width == 0:
            output.append('\n')
            
    output.append("\x1b[0m")
    return "".join(output)

def load_image(input_filepath, desired_width, resize_image):
    try:
        img = Image.open(input_filepath)
    except Exception:
        sys.stderr.write("Could not load image \n")
        sys.exit(1)
        
    img = img.convert("RGB")
    width, height = img.size
    
    if resize_image:
        if desired_width <= 0:
            sys.stderr.write("Argument 'width' must be greater than 0 \n")
            sys.exit(1)
        elif desired_width > width:
            sys.stderr.write(f"Argument 'width' can not be greater than the original image width ({width}px) \n")
            sys.exit(1)
        
        desired_height = int(height / (width / float(desired_width)) / 2)
    else:
        desired_width = width
        desired_height = int(height / 2)
        
    img_resized = img.resize((desired_width, desired_height), Image.Resampling.BILINEAR)
    pixel_data = img_resized.load()
    pixels = [pixel_data[x, y] for y in range(desired_height) for x in range(desired_width)]
    return pixels, desired_width, desired_height

def main():
    if len(sys.argv) == 1:
        sys.stdout.write("No input file\n")
        show_usage()
        sys.exit(1)
        
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hi:o:w:c:gprd", [
            "help", "input=", "output=", "width=", "chars=", "grayscale", "print", "reverse", "debug"
        ])
    except getopt.GetoptError as err:
        sys.stdout.write(f"{err}\n")
        sys.stdout.write("\nHint: Use the \x1b[1m--help\x1b[0m option to get help about the usage \n\n")
        sys.exit(1)
        
    input_filepath = None
    output_filepath = None
    characters = "$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1{}[]?-_+~<>i!lI;:,\"^`'. "
    desired_width = 0
    flags = 0
    resize_image = False
    
    for o, a in opts:
        if o in ("-h", "--help"):
            show_usage()
            sys.exit(1)
        elif o in ("-i", "--input"):
            input_filepath = a
        elif o in ("-o", "--output"):
            output_filepath = a
        elif o in ("-w", "--width"):
            desired_width = atoi(a)
            resize_image = True
        elif o in ("-c", "--chars"):
            if len(a) != 0:
                characters = a
        elif o in ("-g", "--grayscale"):
            flags |= GRAYSCALE_FLAG
        elif o in ("-p", "--print"):
            flags |= PRINT_FLAG
        elif o in ("-r", "--reverse"):
            flags |= REVERSE_FLAG
        elif o in ("-d", "--debug"):
            flags |= DEBUG_FLAG
            
    if input_filepath is None:
        sys.stdout.write("No input file\n")
        show_usage()
        sys.exit(1)
        
    if output_filepath is None:
        flags |= PRINT_FLAG
        
    # Load and scale image
    pixels, width, height = load_image(input_filepath, desired_width, resize_image)
    
    # Reverse string of characters if REVERSE_FLAG is set
    if flags & REVERSE_FLAG:
        characters = characters[::-1]
        
    # Generate output
    if flags & GRAYSCALE_FLAG:
        output = get_output_grayscale(pixels, width, height, characters)
    else:
        output = get_output_rgb(pixels, width, height, characters)
        
    # Print debug information if requested
    if flags & DEBUG_FLAG:
        sys.stdout.write(
            f"Input: {input_filepath} \n"
            f"Output: {output_filepath if output_filepath is not None else 'stdout'} \n"
            f"Resolution: {width}x{height} \n"
            f"Characters ({len(characters)}): \"{characters}\" \n"
        )
        
    # Print to console
    if flags & PRINT_FLAG:
        sys.stdout.write(output)
        
    # Write to output file
    if output_filepath is not None:
        try:
            with open(output_filepath, "w", encoding="utf-8") as f:
                f.write(output)
        except Exception as e:
            sys.stderr.write(f"Could not create an output file: {e} \n")
            sys.exit(1)

if __name__ == "__main__":
    main()
