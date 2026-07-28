#!/usr/bin/env python3
"""
Asciiquarium - An aquarium animation in ASCII art (Python Conversion)
Original Perl Author: Kirk Baucom <kbaucom@schizoid.com>
Contributors: Joan Stark, Claudio Matsuoka
Converted to Python with full feature preservation.
"""

import sys
import os
import time
import random
import argparse
import curses

COLOR_MAP = {}

DEPTH = {
    'guiText': 0,
    'gui': 1,
    'shark': 2,
    'fish_start': 3,
    'fish_end': 20,
    'seaweed': 21,
    'castle': 22,
    'water_line3': 2,
    'water_gap3': 3,
    'water_line2': 4,
    'water_gap2': 5,
    'water_line1': 6,
    'water_gap1': 7,
    'water_line0': 8,
    'water_gap0': 9,
}

def init_colors():
    global COLOR_MAP
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()

    # Pair IDs: 1: CYAN, 2: RED, 3: YELLOW, 4: BLUE, 5: GREEN, 6: MAGENTA, 7: WHITE, 8: BLACK
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_RED, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_BLUE, -1)
    curses.init_pair(5, curses.COLOR_GREEN, -1)
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)
    curses.init_pair(7, curses.COLOR_WHITE, -1)
    curses.init_pair(8, curses.COLOR_BLACK, -1)

    COLOR_MAP = {
        'c': curses.color_pair(1), 'C': curses.color_pair(1), 'cyan': curses.color_pair(1), 'CYAN': curses.color_pair(1),
        'r': curses.color_pair(2), 'R': curses.color_pair(2), 'red': curses.color_pair(2), 'RED': curses.color_pair(2),
        'y': curses.color_pair(3), 'Y': curses.color_pair(3), 'yellow': curses.color_pair(3), 'YELLOW': curses.color_pair(3),
        'b': curses.color_pair(4), 'B': curses.color_pair(4), 'blue': curses.color_pair(4), 'BLUE': curses.color_pair(4),
        'g': curses.color_pair(5), 'G': curses.color_pair(5), 'green': curses.color_pair(5), 'GREEN': curses.color_pair(5),
        'm': curses.color_pair(6), 'M': curses.color_pair(6), 'magenta': curses.color_pair(6), 'MAGENTA': curses.color_pair(6),
        'w': curses.color_pair(7), 'W': curses.color_pair(7), 'white': curses.color_pair(7), 'WHITE': curses.color_pair(7),
        'k': curses.color_pair(8), 'K': curses.color_pair(8), 'black': curses.color_pair(8), 'BLACK': curses.color_pair(8),
    }

def get_color_attr(char_code):
    return COLOR_MAP.get(char_code, COLOR_MAP.get('WHITE', 0))

class Entity:
    def __init__(self, name="", type_name="", shape=None, color=None, position=None,
                 depth=0, callback=None, callback_args=None, die_offscreen=False,
                 die_time=None, die_frame=None, death_cb=None, physical=False,
                 coll_handler=None, default_color='WHITE', auto_trans=True, transparent=' '):
        self.name = name or f"entity_{id(self)}"
        self.type = type_name
        
        if isinstance(shape, str):
            self.shapes = [shape]
        elif isinstance(shape, list):
            self.shapes = shape
        else:
            self.shapes = [""]

        if isinstance(color, str):
            self.colors = [color]
        elif isinstance(color, list):
            self.colors = color
        else:
            self.colors = []

        self.position = list(position) if position else [0, 0, 0] # [x, y, z]
        self.depth = depth
        self.callback = callback
        self.callback_args = callback_args or [0, 0, 0, 0] # [dx, dy, dz, delay]
        self.die_offscreen = die_offscreen
        self.die_time = die_time
        self.die_frame = die_frame
        self.death_cb = death_cb
        self.physical = physical
        self.coll_handler = coll_handler
        self.default_color = default_color
        self.auto_trans = auto_trans
        self.transparent = transparent

        self.current_frame = 0
        self.frame_counter = 0
        self.life_frames = 0
        self.dead = False
        self._collisions = []

    @property
    def x(self):
        return self.position[0]
    @x.setter
    def x(self, val):
        self.position[0] = val

    @property
    def y(self):
        return self.position[1]
    @y.setter
    def y(self, val):
        self.position[1] = val

    @property
    def z(self):
        return self.position[2]
    @z.setter
    def z(self, val):
        self.position[2] = val

    def get_current_shape(self):
        return self.shapes[self.current_frame % len(self.shapes)]

    def get_current_color(self):
        if not self.colors:
            return ""
        return self.colors[self.current_frame % len(self.colors)]

    def size(self):
        lines = self.get_current_shape().strip('\n').split('\n')
        height = len(lines)
        width = max((len(line) for line in lines), default=0)
        return [width, height]

    @property
    def width(self):
        return self.size()[0]

    @property
    def height(self):
        return self.size()[1]

    def collisions(self):
        return self._collisions

    def kill(self):
        self.dead = True

    def move_entity(self, anim):
        dx, dy, dz = self.callback_args[0], self.callback_args[1], self.callback_args[2]
        self.x += dx
        self.y += dy
        self.z += dz
        return True

    def update(self, anim):
        if self.dead:
            return

        self.life_frames += 1

        if self.die_time is not None and time.time() >= self.die_time:
            self.kill()
            return

        if self.die_frame is not None and self.life_frames >= self.die_frame:
            self.kill()
            return

        frame_delay = self.callback_args[3] if len(self.callback_args) > 3 else 0
        if frame_delay > 0:
            self.frame_counter += frame_delay
            if self.frame_counter >= 1.0:
                self.current_frame = (self.current_frame + int(self.frame_counter)) % len(self.shapes)
                self.frame_counter %= 1.0

        if self.callback:
            self.callback(self, anim)
        else:
            self.move_entity(anim)

        if self.die_offscreen:
            w, h = self.width, self.height
            ix, iy = int(self.x), int(self.y)
            if ix + w < 0 or ix >= anim.width() or iy + h < 0 or iy >= anim.height():
                self.kill()

class TermAnimation:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.entities = []
        self._color_enabled = True

    def color(self, val):
        self._color_enabled = bool(val)

    def width(self):
        h, w = self.stdscr.getmaxyx()
        return w

    def height(self):
        h, w = self.stdscr.getmaxyx()
        return h

    def new_entity(self, **kwargs):
        ent = Entity(**kwargs)
        self.add_entity(ent)
        return ent

    def add_entity(self, entity):
        self.entities.append(entity)

    def del_entity(self, entity):
        if entity in self.entities:
            entity.dead = True
            self.entities.remove(entity)

    def get_entities_of_type(self, type_name):
        return [e for e in self.entities if e.type == type_name and not e.dead]

    def remove_all_entities(self):
        for e in self.entities:
            e.dead = True
        self.entities.clear()

    def update_term_size(self):
        pass

    def check_collisions(self):
        physical_entities = [e for e in self.entities if e.physical and not e.dead]
        for e in physical_entities:
            e._collisions.clear()

        n = len(physical_entities)
        for i in range(n):
            e1 = physical_entities[i]
            if e1.dead:
                continue
            w1, h1 = e1.width, e1.height
            x1, y1 = int(e1.x), int(e1.y)

            for j in range(i + 1, n):
                e2 = physical_entities[j]
                if e2.dead:
                    continue
                w2, h2 = e2.width, e2.height
                x2, y2 = int(e2.x), int(e2.y)

                if (x1 < x2 + w2 and x1 + w1 > x2 and y1 < y2 + h2 and y1 + h1 > y2):
                    e1._collisions.append(e2)
                    e2._collisions.append(e1)

        for e in physical_entities:
            if not e.dead and e.coll_handler and e._collisions:
                e.coll_handler(e, self)

    def animate(self):
        for e in list(self.entities):
            if not e.dead:
                e.update(self)

        self.check_collisions()

        dead_entities = [e for e in self.entities if e.dead]
        for e in dead_entities:
            if e in self.entities:
                self.entities.remove(e)
            if e.death_cb:
                e.death_cb(e, self)

    def redraw_screen(self):
        w = self.width()
        h = self.height()
        if w < 10 or h < 5:
            return

        canvas = [[(' ', get_color_attr('WHITE')) for _ in range(w)] for _ in range(h)]

        sorted_entities = sorted(
            [e for e in self.entities if not e.dead],
            key=lambda e: (e.z, e.depth),
            reverse=True
        )

        for ent in sorted_entities:
            shape_str = ent.get_current_shape().strip('\n')
            color_str = ent.get_current_color().strip('\n')

            shape_lines = shape_str.split('\n')
            color_lines = color_str.split('\n') if color_str else []

            pos_x = int(ent.x)
            pos_y = int(ent.y)
            def_attr = get_color_attr(ent.default_color)

            for r, line in enumerate(shape_lines):
                cy = pos_y + r
                if cy < 0 or cy >= h:
                    continue

                col_line = color_lines[r] if r < len(color_lines) else ""

                for c, char in enumerate(line):
                    cx = pos_x + c
                    if cx < 0 or cx >= w:
                        continue

                    if ent.auto_trans and char == ent.transparent:
                        continue

                    attr = def_attr
                    if col_line and c < len(col_line):
                        mask_ch = col_line[c]
                        if mask_ch != ' ':
                            attr = get_color_attr(mask_ch)

                    canvas[cy][cx] = (char, attr)

        self.stdscr.erase()
        for y in range(h):
            for x in range(w):
                ch, attr = canvas[y][x]
                try:
                    self.stdscr.addch(y, x, ch, attr)
                except curses.error:
                    pass

        self.stdscr.refresh()


# --- Asciiquarium ASCII Art & Logic ---

def rand_color(mask):
    colors = ['c', 'C', 'r', 'R', 'y', 'Y', 'b', 'B', 'g', 'G', 'm', 'M']
    res = list(mask)
    for i in range(1, 10):
        digit = str(i)
        if digit in mask:
            c = random.choice(colors)
            res = [c if ch == digit else ch for ch in res]
    return "".join(res)

def add_environment(anim):
    water_line_segment = [
        r"~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~",
        r"^^^^ ^^^  ^^^   ^^^    ^^^^      ",
        r"^^^^      ^^^^     ^^^    ^^     ",
        r"^^      ^^^^      ^^^    ^^^^^^  "
    ]

    segment_size = len(water_line_segment[0])
    segment_repeat = (anim.width() // segment_size) + 2

    tiled_segments = [seg * segment_repeat for seg in water_line_segment]

    for i in range(len(tiled_segments)):
        anim.new_entity(
            name=f"water_seg_{i}",
            type_name="waterline",
            shape=tiled_segments[i],
            position=[0, i + 5, DEPTH[f'water_line{i}']],
            default_color='cyan',
            depth=22,
            physical=True,
        )

def add_castle(anim):
    castle_image = r"""
               T~~
               |
              /^\
             /   \
 _   _   _  /     \  _   _   _
[ ]_[ ]_[ ]/ _   _ \[ ]_[ ]_[ ]
|_=__-_ =_|_[ ]_[ ]_|_=-___-__|
 | _- =  | =_ = _    |= _=   |
 |= -[]  |- = _ =    |_-=_[] |
 | =_    |= - ___    | =_ =  |
 |=  []- |-  /| |\   |=_ =[] |
 |- =_   | =| | | |  |- = -  |
 |_______|__|_|_|_|__|_______|
"""

    castle_mask = r"""
                RR

              yyy
             y   y
            y     y
           y       y



              yyy
             yy yy
            y y y y
            yyyyyyy
"""

    anim.new_entity(
        name="castle",
        shape=castle_image,
        color=castle_mask,
        position=[anim.width() - 32, anim.height() - 13, DEPTH['castle']],
        default_color='BLACK',
    )

def add_all_seaweed(anim):
    seaweed_count = int(anim.width() / 15)
    for _ in range(seaweed_count):
        add_seaweed(None, anim)

def add_seaweed(old_seaweed, anim):
    height = random.randint(0, 3) + 3
    frame0 = ""
    frame1 = ""
    for i in range(1, height + 1):
        left_side = i % 2
        if left_side:
            frame0 += "(\n"
            frame1 += " )\n"
        else:
            frame0 += " )\n"
            frame1 += "(\n"

    x = random.randint(0, max(1, anim.width() - 3)) + 1
    y = anim.height() - height
    anim_speed = random.uniform(0, 0.05) + 0.25
    die_time = time.time() + random.randint(0, 4 * 60) + (8 * 60)

    anim.new_entity(
        name=f"seaweed_{random.random()}",
        shape=[frame0, frame1],
        position=[x, y, DEPTH['seaweed']],
        callback_args=[0, 0, 0, anim_speed],
        die_time=die_time,
        death_cb=add_seaweed,
        default_color='green',
    )

def add_bubble(fish, anim):
    cb_args = fish.callback_args
    fish_size = fish.size()
    bubble_pos = list(fish.position)

    if cb_args[0] > 0:
        bubble_pos[0] += fish_size[0]

    bubble_pos[1] += int(fish_size[1] / 2)
    bubble_pos[2] -= 1

    anim.new_entity(
        shape=['.', 'o', 'O', 'O', 'O'],
        type_name='bubble',
        position=bubble_pos,
        callback_args=[0, -1, 0, 0.1],
        die_offscreen=True,
        physical=True,
        coll_handler=bubble_collision,
        default_color='CYAN',
    )

def bubble_collision(bubble, anim):
    for col_obj in bubble.collisions():
        if col_obj.type == 'waterline':
            bubble.kill()
            break

def add_all_fish(anim, new_fish=True):
    screen_size = (anim.height() - 9) * anim.width()
    fish_count = int(screen_size / 350)
    for _ in range(fish_count):
        add_fish(None, anim, new_fish)

def add_fish(old_fish, anim, new_fish=True):
    if new_fish and random.randint(0, 11) > 8:
        add_new_fish(old_fish, anim)
    else:
        add_old_fish(old_fish, anim)

def add_new_fish(old_fish, anim):
    fish_image = [
r"""
   \
  / \
>=_('>
  \_/
   /
""",
r"""
   1
  1 1
663745
  111
   3
""",
r"""
  /
 / \
<')_=<
 \_/
  \
""",
r"""
  2
 111
547366
 111
  3
""",
r"""
     ,
     \}\
\  .'  `\
}}<   ( 6>
/  `,  .'
     \}/
     '
""",
r"""
     2
     22
6  11  11
661   7 45
6  11  11
     33
     3
""",
r"""
    ,
   /\{
 /'  `.  /
<6 )   >\{\{
 `.  ,'  \
   \}
    `
""",
r"""
    2
   22
 11  11  6
54 7   166
 11  11  6
   33
    3
""",
r"""
            \'`.
             )  \
(`.??????_.-`' ' '`-.
 \ `.??.`        (o) \_
  >  ><     (((       (
 / .`??`._      /_|  /'
(.`???????`-. _  _.-`
            /__/'
""",
r"""
            1111
             1  1
111      11111 1 1111
 1 11  11        141 11
  1  11     777       5
 1 11  111      333  11
111       111 1  1111
            11111
""",
r"""
       .'`/
      /  (
  .-'` ` `'-._??????.')
_/ (o)        '.??.' /
)       )))     ><  <
`\  |_\      _.'??'. \
  '-._  _ .-'???????'.)
      `\__\
""",
r"""
       1111
      1  1
  1111 1 11111      111
11 141        11  11 1
5       777     11  1
11  333      111  11 1
  1111  1 111       111
      11111
""",
r"""
       ,--,_
__    _\.---'-.
\ '.-"     // o\
/_.'-._    \\  /
       `"--(/"`
""",
r"""
       22222
66    121111211
6 6111     77 41
6661111    77  1
       11113311
""",
r"""
    _,--,
 .-'---./_    __
/o \\     "-.' /
\  //    _.-'._\
 `"Downloads)--"`
""",
r"""
    22222
 112111121    66
14 77     1116 6
1  77    1111666
 11331111
"""
    ]
    add_fish_entity(anim, fish_image)

def add_old_fish(old_fish, anim):
    fish_image = [
r"""
       \
     ...\..,
\  /'       \
 >=     (  ' >
/  \      / /
    `"'"'/''
""",
r"""
       2
     1112111
6  11       1
 66     7  4 5
6  1      3 1
    11111311
""",
r"""
      /
  ,../...
 /       '\  /
< '  )     =<
 \ \      /  \
  `'\'"'"'
""",
r"""
      2
  1112111
 1       11  6
5 4  7     66
 1 3      1  6
  11311111
""",
r"""
    \
\ /--\
>=  (o>
/ \__/
    /
""",
r"""
    2
6 1111
66  745
6 1111
    3
""",
r"""
  /
 /--\ /
<o)  =<
 \__/ \
  \
""",
r"""
  2
 1111 6
547  66
 1111 6
  3
""",
r"""
       \:.
\;,   ,;\\\\\,,
  \\\\\;;:::::::o
  ///;;::::::::<
 /;` ``/////``
""",
r"""
       222
666   1122211
  6661111111114
  66611111111115
 666 113333311
""",
r"""
      .:/
   ,,///;,   ,;/
 o:::::::;;///
>::::::::;;\\\\\
  ''\\\\\\\\\'' ';\
""",
r"""
      222
   1122211   666
 4111111111666
51111111111666
  113333311 666
""",
r"""
  __
><_'>
   '
""",
r"""
  11
61145
   3
""",
r"""
 __
<'_><
 `
""",
r"""
 11
54116
 3
""",
r"""
   ..\,
>='   ('>
  '''/''
""",
r"""
   1121
661   745
  111311
""",
r"""
  ,/..
<')   `=<
 ``\```
""",
r"""
  1211
547   166
 113111
""",
r"""
   \
  / \
>=_('>
  \_/
   /
""",
r"""
   2
  1 1
661745
  111
   3
""",
r"""
  /
 / \
<')_=<
 \_/
  \
""",
r"""
  2
 1 1
547166
 111
  3
""",
r"""
  ,\
>=('>
  '/
""",
r"""
  12
66745
  13
""",
r"""
 /,
<')=<
 \`
""",
r"""
 21
54766
 31
""",
r"""
  __
\/ o\
/\__/
""",
r"""
  11
61 41
61111
""",
r"""
 __
/o \/
\__/\
""",
r"""
 11
14 16
11116
"""
    ]
    add_fish_entity(anim, fish_image)

def add_fish_entity(anim, fish_image):
    fish_num = random.randint(0, (len(fish_image) // 2) - 1)
    fish_index = fish_num * 2
    speed = random.uniform(0, 2) + 0.25
    depth = random.randint(DEPTH['fish_start'], DEPTH['fish_end'] - 1)

    color_mask = fish_image[fish_index + 1]
    color_mask = color_mask.replace('4', 'W')
    color_mask = rand_color(color_mask)

    if fish_num % 2 != 0:
        speed *= -1

    fish_obj = Entity(
        type_name='fish',
        shape=fish_image[fish_index],
        auto_trans=True,
        color=color_mask,
        position=[0, 0, depth],
        callback=fish_callback,
        callback_args=[speed, 0, 0],
        die_offscreen=True,
        death_cb=add_fish,
        physical=True,
        coll_handler=fish_collision,
    )

    max_height = 9
    min_height = max(max_height + 1, anim.height() - fish_obj.height)
    fish_obj.y = random.randint(max_height, min_height - 1)

    if fish_num % 2 != 0:
        fish_obj.x = anim.width() - 2
    else:
        fish_obj.x = 1 - fish_obj.width

    anim.add_entity(fish_obj)

def fish_callback(fish, anim):
    if random.randint(0, 99) > 97:
        add_bubble(fish, anim)
    return fish.move_entity(anim)

def fish_collision(fish, anim):
    for col_obj in fish.collisions():
        if col_obj.type == 'teeth' and fish.height <= 5:
            add_splat(anim, col_obj.position[0], col_obj.position[1], col_obj.position[2])
            fish.kill()
            break

def add_splat(anim, x, y, z):
    splat_image = [
r"""

   .
  ***
   '

""",
r"""

 ",*;`
 "*,**
 *"'~'

""",
r"""
  , ,
 " ","'
 *" *'"
  " ; .

""",
r"""
* ' , ' `
' ` * . '
 ' `' ",'
* ' " * .
" * ', '
"""
    ]

    anim.new_entity(
        shape=splat_image,
        position=[x - 4, y - 2, z - 2],
        default_color='RED',
        callback_args=[0, 0, 0, 0.25],
        transparent=' ',
        die_frame=15,
    )

def add_shark(old_ent, anim):
    shark_image = [
r"""
                              __
                             ( `\
  ,??????????????????????????)   `\
;' `.????????????????????????(     `\__
 ;   `.?????????????__..---''          `~~~~-._
  `.   `.____...--''                       (b  `--._
    >                     _.-'      .((      ._     )
  .`.-`--...__         .-'     -.___.....-(|/|/|/|/'
 ;.'?????????`. ...----`.___.',,,_______......---'
 '???????????'-'
""",
r"""
                     __
                    /' )
                  /'   (??????????????????????????,
              __/'     )????????????????????????.' `;
      _.-~~~~'          ``---..__?????????????.'   ;
 _.--'  b)                       ``--...____.'   .'
(     _.      )).      `-._                     <
 `\|\|\|\|)-.....___.-     `-.         __...--'-.'.
   `---......_______,,,`.___.'----... .'?????????`.;
                                     `-`???????????`
"""
    ]

    shark_mask = [
r"""





                                           cR

                                          cWWWWWWWW


""",
r"""





        Rc

  WWWWWWWWc


"""
    ]

    dir_flag = random.randint(0, 1)
    x = -53
    y = random.randint(9, max(10, anim.height() - 19))
    teeth_x = -9
    teeth_y = y + 7
    speed = 2.0

    if dir_flag:
        speed *= -1
        x = anim.width() - 2
        teeth_x = x + 9

    anim.new_entity(
        type_name='teeth',
        shape="*",
        position=[teeth_x, teeth_y, DEPTH['shark'] + 1],
        depth=DEPTH['fish_end'] - DEPTH['fish_start'],
        callback_args=[speed, 0, 0],
        physical=True,
    )

    anim.new_entity(
        type_name="shark",
        color=shark_mask[dir_flag],
        shape=shark_image[dir_flag],
        auto_trans=True,
        position=[x, y, DEPTH['shark']],
        default_color='CYAN',
        callback_args=[speed, 0, 0],
        die_offscreen=True,
        death_cb=shark_death,
    )

def shark_death(shark, anim):
    for obj in anim.get_entities_of_type('teeth'):
        anim.del_entity(obj)
    random_object(shark, anim)

def add_ship(old_ent, anim):
    ship_image = [
r"""
     |    |    |
    )_)  )_)  )_)
   )___))___))___)\
  )____)____)_____)\\\
_____|____|____|____\\\\\__
\                   /
""",
r"""
         |    |    |
        (_(  (_(  (_(
      /(___((___((___(
    //(_____(____(____(
__///____|____|____|_____
    \                   /
"""
    ]

    ship_mask = [
r"""
     y    y    y

                  w
                   ww
yyyyyyyyyyyyyyyyyyyywwwyy
y                   y
""",
r"""
         y    y    y

      w
    ww
yywwwyyyyyyyyyyyyyyyyyyyy
    y                   y
"""
    ]

    dir_flag = random.randint(0, 1)
    x = -24
    speed = 1.0
    if dir_flag:
        speed *= -1
        x = anim.width() - 2

    anim.new_entity(
        color=ship_mask[dir_flag],
        shape=ship_image[dir_flag],
        auto_trans=True,
        position=[x, 0, DEPTH['water_gap1']],
        default_color='WHITE',
        callback_args=[speed, 0, 0],
        die_offscreen=True,
        death_cb=random_object,
    )

def add_whale(old_ent, anim):
    whale_image = [
r"""
        .-----:
      .'       `.
,????/       (o) \
\`._/          ,__)
""",
r"""
    :-----.
  .'       `.
 / (o)       \????,
(__,          \_.'/
"""
    ]

    whale_mask = [
r"""
             C C
           CCCCCCC
           C  C  C
        BBBBBBB
      BB       BB
B    B       BWB B
BBBBB          BBBB
""",
r"""
   C C
 CCCCCCC
 C  C  C
    BBBBBBB
  BB       BB
 B BWB       B    B
BBBB          BBBBB
"""
    ]

    water_spout = [
"\n\n   :",
"\n   :\n   :",
"  . .\n  -:-\n   :",
"  . .\n .-:-.\n   :",
"  . .\n'.-:-.`\n'  :  '",
"\n .- -.\n;  :  ;",
"\n\n;     ;"
    ]

    dir_flag = random.randint(0, 1)
    speed = 1.0

    if dir_flag:
        spout_align = 1
        speed *= -1
        x = anim.width() - 2
    else:
        spout_align = 11
        x = -18

    whale_anim = []
    whale_anim_mask = []

    for _ in range(5):
        whale_anim.append("\n\n\n" + whale_image[dir_flag])
        whale_anim_mask.append(whale_mask[dir_flag])

    for spout_frame in water_spout:
        aligned_lines = [(" " * spout_align + line) for line in spout_frame.split("\n")]
        aligned_spout = "\n".join(aligned_lines) + "\n"
        whale_anim.append(aligned_spout + whale_image[dir_flag])
        whale_anim_mask.append(whale_mask[dir_flag])

    anim.new_entity(
        color=whale_anim_mask,
        shape=whale_anim,
        auto_trans=True,
        position=[x, 0, DEPTH['water_gap2']],
        default_color='WHITE',
        callback_args=[speed, 0, 0, 1],
        die_offscreen=True,
        death_cb=random_object,
    )

def add_monster(old_ent, anim, new_monster=True):
    if new_monster:
        add_new_monster(old_ent, anim)
    else:
        add_old_monster(old_ent, anim)

def add_new_monster(old_ent, anim):
    monster_image = [
        [
r"""
         _???_?????????????????????_???_???????_a_a
       _{.`=`.}_??????_???_??????_{.`=`.}_????{/ ''\_
 _????{.'  _  '.}????{.`'`.}????{.'  _  '.}??{|  ._oo)
{ \??{/  .'?'.  \}??{/ .-. \}??{/  .'?'.  \}?{/  |
""",
r"""
                      _???_????????????????????_a_a
  _??????_???_??????_{.`=`.}_??????_???_??????{/ ''\_
 { \????{.`'`.}????{.'  _  '.}????{.`'`.}????{|  ._oo)
  \ \??{/ .-. \}??{/  .'?'.  \}??{/ .-. \}???{/  |
"""
        ],
        [
r"""
   a_a_???????_???_?????????????????????_???_
 _/'' \}????_{.`=`.}_??????_???_??????_{.`=`.}_
(oo_.  |}??{.'  _  '.}????{.`'`.}????{.'  _  '.}????_
    |  \}?{/  .'?'.  \}??{/ .-. \}??{/  .'?'.  \}??/ }
""",
r"""
   a_a_????????????????????_   _
 _/'' \}??????_???_??????_{.`=`.}_??????_???_??????_
(oo_.  |}????{.`'`.}????{.'  _  '.}????{.`'`.}????/ }
    |  \}???{/ .-. \}??{/  .'?'.  \}??{/ .-. \}??/ /
"""
        ]
    ]

    monster_mask = [
r"""                                                W W



""",
r"""
   W W



"""
    ]

    dir_flag = random.randint(0, 1)
    speed = 2.0
    if dir_flag:
        speed *= -1
        x = anim.width() - 2
    else:
        x = -54

    anim_mask = [monster_mask[dir_flag]] * 2

    anim.new_entity(
        shape=monster_image[dir_flag],
        auto_trans=True,
        color=anim_mask,
        position=[x, 2, DEPTH['water_gap2']],
        callback_args=[speed, 0, 0, 0.25],
        death_cb=random_object,
        die_offscreen=True,
        default_color='GREEN',
    )

def add_old_monster(old_ent, anim):
    monster_image = [
        [
r"""
                                                          ____
            __??????????????????????????????????????????/   o  \
          /    \????????_?????????????????????_???????/     ____ >
  _??????|  __  |?????/   \????????_????????/   \????|     |
 | \?????|  ||  |????|     |?????/   \?????|     |???|     |
""",
r"""
                                                          ____
                                             __?????????/   o  \
             _?????????????????????_???????/    \?????/     ____ >
   _???????/   \????????_????????/   \????|  __  |???|     |
  | \?????|     |?????/   \?????|     |???|  ||  |???|     |
""",
r"""
                                                          ____
                                  __????????????????????/   o  \
 _??????????????????????_???????/    \????????_???????/     ____ >
| \??????????_????????/   \????|  __  |?????/   \????|     |
 \ \???????/   \?????|     |???|  ||  |????|     |???|     |
""",
r"""
                                                          ____
                       __???????????????????????????????/   o  \
  _??????????_???????/    \????????_??????????????????/     ____ >
 | \???????/   \????|  __  |?????/   \????????_??????|     |
  \ \?????|     |???|  ||  |????|     |?????/   \????|     |
"""
        ],
        [
r"""
    ____
  /  o   \??????????????????????????????????????????__
< ____     \???????_?????????????????????_????????/    \
      |     |????/   \????????_????????/   \?????|  __  |??????_
      |     |???|     |?????/   \?????|     |????|  ||  |?????/ |
""",
r"""
    ____
  /  o   \?????????__
< ____     \?????/    \???????_?????????????????????_
      |     |???|  __  |????/   \????????_????????/   \???????_
      |     |???|  ||  |???|     |?????/   \?????|     |?????/ |
""",
r"""
    ____
  /  o   \????????????????????__
< ____     \???????_????????/    \???????_??????????????????????_
      |     |????/   \?????|  __  |????/   \????????_??????????/ |
      |     |???|     |????|  ||  |???|     |?????/   \???????/ /
""",
r"""
    ____
  /  o   \???????????????????????????????__
< ____     \??????????????????_????????/    \???????_??????????_
      |     |??????_????????/   \?????|  __  |????/   \???????/ |
      |     |????/   \?????|     |????|  ||  |???|     |?????/ /
"""
        ]
    ]

    monster_mask = [
r"""

                                                            W



""",
r"""

     W



"""
    ]

    dir_flag = random.randint(0, 1)
    speed = 2.0
    if dir_flag:
        speed *= -1
        x = anim.width() - 2
    else:
        x = -64

    anim_mask = [monster_mask[dir_flag]] * 4

    anim.new_entity(
        shape=monster_image[dir_flag],
        auto_trans=True,
        color=anim_mask,
        position=[x, 2, DEPTH['water_gap2']],
        callback_args=[speed, 0, 0, 0.25],
        death_cb=random_object,
        die_offscreen=True,
        default_color='GREEN',
    )

def add_big_fish(old_ent, anim, new_fish=True):
    if new_fish and random.randint(0, 2) > 1:
        add_big_fish_2(old_ent, anim)
    else:
        add_big_fish_1(old_ent, anim)

def add_big_fish_1(old_ent, anim):
    big_fish_image = [
r"""
 ______
`""-.  `````-----.....__
     `.  .      .       `-.
       :     .     .       `.
 ,?????:   .    .          _ :
: `.???:                  (@) `._
 `. `..'     .     =`-.       .__)
   ;     .        =  ~  :     .-"
 .' .'`.   .    .  =.-'  `._ .'
: .'???:               .   .'
 '???.'  .    .     .   .-'
   .'____....----''.'=.'
   ""?????????????.'.'
               ''"'`
""",
r"""
                           ______
          __.....-----'''''  .-""'
       .-'       .      .  .'
     .'       .     .     :
    : _          .    .   :?????,
 _.' (@)                  :???.' :
(__.       .-'=     .     `..' .'
 "-.     :  ~  =        .     ;
   `. _.'  `-.=  .    .   .'`. `.
     `.   .               :???`. :
       `-.   .     .    .  `.???`
          `.=`.``----....____`.
            `.`.?????????????""
              '`"``
"""
    ]

    big_fish_mask = [
r"""
 111111
11111  11111111111111111
     11  2      2       111
       1     2     2       11
 1     1   2    2          1 1
1 11   1                  1W1 111
 11 1111     2     1111       1111
   1     2        1  1  1     111
 11 1111   2    2  1111  111 11
1 11   1               2   11
 1   11  2    2     2   111
   111111111111111111111
   11             1111
               11111
""",
r"""
                           111111
          11111111111111111  11111
       111       2      2  11
     11       2     2     1
    1 1          2    2   1     1
 111 1W1                  1   11 1
1111       1111     2     1111 11
 111     1  1  1        2     1
   11 111  1111  2    2   1111 11
     11   2               1   11 1
       111   2     2    2  11   1
          111111111111111111111
            1111             11
              11111
"""
    ]

    dir_flag = random.randint(0, 1)
    speed = 3.0
    if dir_flag:
        x = anim.width() - 1
        speed *= -1
    else:
        x = -34

    max_height = 9
    min_height = max(max_height + 1, anim.height() - 15)
    y = random.randint(max_height, min_height - 1)
    color_mask = rand_color(big_fish_mask[dir_flag])

    anim.new_entity(
        shape=big_fish_image[dir_flag],
        auto_trans=True,
        color=color_mask,
        position=[x, y, DEPTH['shark']],
        callback_args=[speed, 0, 0],
        death_cb=random_object,
        die_offscreen=True,
        default_color='YELLOW',
    )

def add_big_fish_2(old_ent, anim):
    big_fish_image = [
r"""
                _ _ _
             .='\\ \\ \\`"=,
           .'\\ \\ \\ \\ \\ \\ \\
\'=._?????/ \\ \\ \\_\\_\\_\\_\\_\\
\'=._'.??/\\ \\,-"`- _ - _ - '-.
  \`=._\|'.\/- _ - _ - _ - _- \
  ;"= ._\=./_ -_ -_ \{`"=_    @ \
   ;="_-_=- _ -  _ - \{"=_"-     \
   ;_=_--_.,          \{_.='   .-/
  ;.="` / ';\        _.     _.-`
  /_.='/ \/ /;._ _ _\{.-;`/"`
/._=_.'???'/ / / / /\{.= /
/.=' ??????`'./_/_.=`\{_/
""",
r"""
            _ _ _
        ,="`/ / /'=.
       / / / / / / /'.
      /_/_/_/_/_/ / / \?????_.='/
   .-' - _ - _ -`"-,/ /\??.'_.='/
  / -_ - _ - _ - _ -\/.'|/_.=`/
 / @    _="\} _- _- _\.=/_. =";
/     -"_="\} - _  - _ -=_-_"=;
\-.   '=._\}          ,._--_=_;
 `-._     ._        /;' \ `"=.;
     `"\`;-.\}_ _ _.;\ \/ \'=._\
        \ =.\}\ \ \ \ \'???'._=_.\\
         \_\}`=._\_\.'`???????'=.\\
"""
    ]

    big_fish_mask = [
r"""
                1 1 1
             1111 1 11111
           111 1 1 1 1 1 1
11111     1 1 1 11111111111
1111111  11 111112 2 2 2 2 111
  111111111112 2 2 2 2 2 2 22 1
  111 1111 12 22 22 11111    W 1
   11111112 2 2  2 2 111111     1
   111111111          11111   111
  11111 11111        11     1111
  111111 11 1111 1 111111111
1111111   11 1 1 1 1111 1
1111       1111111111111
""",
r"""
            1 1 1
        11111 1 1111
       1 1 1 1 1 1 111
      11111111111 1 1 1     11111
   111 2 2 2 2 211111 11  1111111
  1 22 2 2 2 2 2 2 211111111111
 1 W    11111 22 22 2111111 111
1     111111 2 2  2 2 21111111
111   11111          111111111
 1111     11        111 1 11111
     111111111 1 1111 11 111111
        1 1111 1 1 1 11   1111111
         1111111111111       1111
"""
    ]

    dir_flag = random.randint(0, 1)
    speed = 2.5
    if dir_flag:
        x = anim.width() - 1
        speed *= -1
    else:
        x = -33

    max_height = 9
    min_height = max(max_height + 1, anim.height() - 14)
    y = random.randint(max_height, min_height - 1)
    color_mask = rand_color(big_fish_mask[dir_flag])

    anim.new_entity(
        shape=big_fish_image[dir_flag],
        auto_trans=True,
        color=color_mask,
        position=[x, y, DEPTH['shark']],
        callback_args=[speed, 0, 0],
        death_cb=random_object,
        die_offscreen=True,
        default_color='YELLOW',
    )

def random_object(dead_object, anim, new_fish=True, new_monster=True):
    subroutines = [
        add_ship,
        add_whale,
        lambda dead_ent, a: add_monster(dead_ent, a, new_monster),
        lambda dead_ent, a: add_big_fish(dead_ent, a, new_fish),
        add_shark,
    ]
    sub = random.choice(subroutines)
    sub(dead_object, anim)


# --- Main Loop ---

def run_asciiquarium(stdscr, classic=False):
    try:
        curses.curs_set(0)
    except Exception:
        pass

    stdscr.nodelay(True)
    stdscr.timeout(100) # 100ms refresh delay (similar to halfdelay(1))
    init_colors()

    new_fish = not classic
    new_monster = not classic

    anim = TermAnimation(stdscr)
    anim.color(1)

    while True:
        add_environment(anim)
        add_castle(anim)
        add_all_seaweed(anim)
        add_all_fish(anim, new_fish=new_fish)
        random_object(None, anim, new_fish=new_fish, new_monster=new_monster)

        paused = False
        redraw = False

        while not redraw:
            try:
                ch = stdscr.getch()
            except Exception:
                ch = -1

            if ch != -1:
                key = chr(ch).lower() if 0 <= ch < 256 else ''
                if key == 'q':
                    return
                elif key == 'r':
                    redraw = True
                    break
                elif key == 'p':
                    paused = not paused

            if not paused:
                anim.animate()

            anim.redraw_screen()

        anim.remove_all_entities()

def main():
    parser = argparse.ArgumentParser(description="Asciiquarium in Python")
    parser.add_argument('-c', '--classic', action='store_true', help='Classic mode (disable new fish & new monster art)')
    parser.add_argument('-v', '--version', action='version', version='asciiquarium 1.1 (Python)')
    args = parser.parse_args()

    try:
        curses.wrapper(lambda stdscr: run_asciiquarium(stdscr, classic=args.classic))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error running Asciiquarium: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
