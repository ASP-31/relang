#!/usr/bin/env node

/**
 * sl.js - Node.js port of Steam Locomotive (sl)
 * Fulfills reLang migration guidelines.
 */

const child_process = require('child_process');

// --- Locomotive Constants & Definitions ---

const D51HEIGHT = 10;
const D51FUNNEL = 7;
const D51LENGTH = 83;
const D51PATTERNS = 6;

const D51STR1 = "      ====        ________                ___________ ";
const D51STR2 = "  _D _|  |_______/        \\\\__I_I_____===__|_________| ";
const D51STR3 = "   |(_)---  |   H\\\\________/ |   |        =|___ ___|   ";
const D51STR4 = "   /     |  |   H  |  |     |   |         ||_| |_||   ";
const D51STR5 = "  |      |  |   H  |__--------------------| [___] |   ";
const D51STR6 = "  | ________|___H__/__|_____/[][]~\\\\_______|       |   ";
const D51STR7 = "  |/ |   |-----------I_____I [][] []  D   |=======|__ ";

const D51WHL11 = "__/ =| o |=-~~\\\\  /~~\\\\  /~~\\\\  /~~\\\\ ____Y___________|__ ";
const D51WHL12 = " |/-=|___|=    ||    ||    ||    |_____/~\\\\___/        ";
const D51WHL13 = "  \\\\_/      \\\\O=====O=====O=====O_/      \\\\_/            ";

const D51WHL21 = "__/ =| o |=-~~\\\\  /~~\\\\  /~~\\\\  /~~\\\\ ____Y___________|__ ";
const D51WHL22 = " |/-=|___|=O=====O=====O=====O   |_____/~\\\\___/        ";
const D51WHL23 = "  \\\\_/      \\\\__/  \\\\__/  \\\\__/  \\\\__/      \\\\_/            ";

const D51WHL31 = "__/ =| o |=-O=====O=====O=====O \\\\ ____Y___________|__ ";
const D51WHL32 = " |/-=|___|=    ||    ||    ||    |_____/~\\\\___/        ";
const D51WHL33 = "  \\\\_/      \\\\__/  \\\\__/  \\\\__/  \\\\__/      \\\\_/            ";

const D51WHL41 = "__/ =| o |=-~O=====O=====O=====O\\\\ ____Y___________|__ ";
const D51WHL42 = " |/-=|___|=    ||    ||    ||    |_____/~\\\\___/        ";
const D51WHL43 = "  \\\\_/      \\\\__/  \\\\__/  \\\\__/  \\\\__/      \\\\_/            ";

const D51WHL51 = "__/ =| o |=-~~\\\\  /~~\\\\  /~~\\\\  /~~\\\\ ____Y___________|__ ";
const D51WHL52 = " |/-=|___|=   O=====O=====O=====O|_____/~\\\\___/        ";
const D51WHL53 = "  \\\\_/      \\\\__/  \\\\__/  \\\\__/  \\\\__/      \\\\_/            ";

const D51WHL61 = "__/ =| o |=-~~\\\\  /~~\\\\  /~~\\\\  /~~\\\\ ____Y___________|__ ";
const D51WHL62 = " |/-=|___|=    ||    ||    ||    |_____/~\\\\___/        ";
const D51WHL63 = "  \\\\_/      \\\\_O=====O=====O=====O/      \\\\_/            ";

const D51DEL = "                                                      ";

const COAL01 = "                              ";
const COAL02 = "                              ";
const COAL03 = "    _________________         ";
const COAL04 = "   _|                \\\\_____A  ";
const COAL05 = " =|                        |  ";
const COAL06 = " -|                        |  ";
const COAL07 = "__|________________________|_ ";
const COAL08 = "|__________________________|_ ";
const COAL09 = "   |_D__D__D_|  |_D__D__D_|   ";
const COAL10 = "    \\\\_/   \\\\_/    \\\\_/   \\\\_/    ";

const COALDEL = "                              ";

const LOGOHEIGHT = 6;
const LOGOFUNNEL = 4;
const LOGOLENGTH = 84;
const LOGOPATTERNS = 6;

const LOGO1 = "     ++      +------ ";
const LOGO2 = "     ||      |+-+ |  ";
const LOGO3 = "   /---------|| | |  ";
const LOGO4 = "  + ========  +-+ |  ";

const LWHL11 = " _|--O========O~\\\\-+  ";
const LWHL12 = "//// \\\\_/      \\\\_/    ";

const LWHL21 = " _|--/O========O\\\\-+  ";
const LWHL22 = "//// \\\\_/      \\\\_/    ";

const LWHL31 = " _|--/~O========O-+  ";
const LWHL32 = "//// \\\\_/      \\\\_/    ";

const LWHL41 = " _|--/~\\\\------/~\\\\-+  ";
const LWHL42 = "//// \\\\_O========O    ";

const LWHL51 = " _|--/~\\\\------/~\\\\-+  ";
const LWHL52 = "//// \\\\O========O/    ";

const LWHL61 = " _|--/~\\\\------/~\\\\-+  ";
const LWHL62 = "//// O========O_/    ";

const LCOAL1 = "____                 ";
const LCOAL2 = "|   \\\\@@@@@@@@@@@     ";
const LCOAL3 = "|    \\\\@@@@@@@@@@@@@_ ";
const LCOAL4 = "|                  | ";
const LCOAL5 = "|__________________| ";
const LCOAL6 = "   (O)       (O)     ";

const LCAR1 = "____________________ ";
const LCAR2 = "|  ___ ___ ___ ___ | ";
const LCAR3 = "|  |_| |_| |_| |_| | ";
const LCAR4 = "|__________________| ";
const LCAR5 = "|__________________| ";
const LCAR6 = "   (O)        (O)    ";

const DELLN = "                     ";

const C51HEIGHT = 11;
const C51FUNNEL = 7;
const C51LENGTH = 87;
const C51PATTERNS = 6;

const C51DEL = "                                                       ";

const C51STR1 = "        ___                                            ";
const C51STR2 = "       _|_|_  _     __       __             ___________";
const C51STR3 = "    D__/   \\\\_(_)___|  |__H__|  |_____I_Ii_()|_________|";
const C51STR4 = "     | `---'   |:: `--'  H  `--'         |  |___ ___|  ";
const C51STR5 = "    +|~~~~~~~~++::~~~~~~~H~~+=====+~~~~~~|~~||_| |_||  ";
const C51STR6 = "    ||        | ::       H  +=====+      |  |::  ...|  ";
const C51STR7 = "|    | _______|_::-----------------[][]-----|       |  ";

const C51WH61 = "| /~~ ||   |-----/~~~~\\\\  /[I_____I][][] --|||_______|__";
const C51WH62 = "------'|oOo|==[]=-     ||      ||      |  ||=======_|__";
const C51WH63 = "/~\\\\____|___|/~\\\\_|   O=======O=======O  |__|+-/~\\\\_|     ";
const C51WH64 = "\\\\_/         \\\\_/  \\\\____/  \\\\____/  \\\\____/      \\\\_/       ";

const C51WH51 = "| /~~ ||   |-----/~~~~\\\\  /[I_____I][][] --|||_______|__";
const C51WH52 = "------'|oOo|===[]=-    ||      ||      |  ||=======_|__";
const C51WH53 = "/~\\\\____|___|/~\\\\_|    O=======O=======O |__|+-/~\\\\_|     ";
const C51WH54 = "\\\\_/         \\\\_/  \\\\____/  \\\\____/  \\\\____/      \\\\_/       ";

const C51WH41 = "| /~~ ||   |-----/~~~~\\\\  /[I_____I][][] --|||_______|__";
const C51WH42 = "------'|oOo|===[]=- O=======O=======O  |  ||=======_|__";
const C51WH43 = "/~\\\\____|___|/~\\\\_|      ||      ||      |__|+-/~\\\\_|     ";
const C51WH44 = "\\\\_/         \\\\_/  \\\\____/  \\\\____/  \\\\____/      \\\\_/       ";

const C51WH31 = "| /~~ ||   |-----/~~~~\\\\  /[I_____I][][] --|||_______|__";
const C51WH32 = "------'|oOo|==[]=- O=======O=======O   |  ||=======_|__";
const C51WH33 = "/~\\\\____|___|/~\\\\_|      ||      ||      |__|+-/~\\\\_|     ";
const C51WH34 = "\\\\_/         \\\\_/  \\\\____/  \\\\____/  \\\\____/      \\\\_/       ";

const C51WH21 = "| /~~ ||   |-----/~~~~\\\\  /[I_____I][][] --|||_______|__";
const C51WH22 = "------'|oOo|=[]=- O=======O=======O    |  ||=======_|__";
const C51WH23 = "/~\\\\____|___|/~\\\\_|      ||      ||      |__|+-/~\\\\_|     ";
const C51WH24 = "\\\\_/         \\\\_/  \\\\____/  \\\\____/  \\\\____/      \\\\_/       ";

const C51WH11 = "| /~~ ||   |-----/~~~~\\\\  /[I_____I][][] --|||_______|__";
const C51WH12 = "------'|oOo|=[]=-      ||      ||      |  ||=======_|__";
const C51WH13 = "/~\\\\____|___|/~\\\\_|  O=======O=======O   |__|+-/~\\\\_|     ";
const C51WH14 = "\\\\_/         \\\\_/  \\\\____/  \\\\____/  \\\\____/      \\\\_/       ";

const man = [
    ["", "(O)"],
    ["Help!", "\\O/"]
];

const fdancer = [
    ["\\\\0", "/\\", "|\\"],
    ["0//", "/\\", "/|"]
];

const Efdancer = [
    ["   ", "  ", "  "],
    ["   ", "  ", "  "]
];

const mdancer = [
    ["_O_", " #", "/\\"],
    ["(0)", " #", "/\\"],
    ["(O_", " #", "/\\"]
];

const Emdancer = [
    ["   ", "  ", "  "],
    ["   ", "  ", "  "],
    ["   ", "  ", "  "]
];

// --- Global Program State ---

let ACCIDENT = 0;
let LOGO = 0;
let FLY = 0;
let C51 = 0;
let DANCE = 0;
let RAND = 0;

let COLS = 0;
let LINES = 0;
let N = 0;

let output_map = [];

// --- Smoke Animation State ---

const SMOKEPTNS = 16;
const Smoke = [
    [
        "(   )", "(    )", "(    )", "(   )", "(  )",
        "(  )", "( )", "( )", "()", "()",
        "O", "O", "O", "O", "O",
        " "
    ],
    [
        "(@@@)", "(@@@@)", "(@@@@)", "(@@@)", "(@@)",
        "(@@)", "(@)", "(@)", "@@", "@@",
        "@", "@", "@", "@", "@",
        " "
    ]
];
const Eraser = [
    "     ", "      ", "      ", "     ", "    ",
    "    ", "   ", "   ", "  ", "  ",
    " ", " ", " ", " ", " ",
    " "
];
const dy = [ 2, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 ];
const dx = [ -2, -1, 0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3 ];

let smokeS = [];
let smokeSum = 0;

// --- Helper Functions for C Compatibility ---

function c_div(a, b) {
    return (a / b) | 0;
}

function c_mod(a, b) {
    let r = a % b;
    return r < 0 ? r + b : r;
}

function count() {
    let min = 0;
    const offset = 21;
    if (LOGO >= 1) {
        min = -LOGOLENGTH - 1 - offset * (LOGO - 1);
    } else if (C51 === 1) {
        min = -C51LENGTH - 1;
    } else {
        min = -D51LENGTH - 1;
    }
    return min;
}

function addchModify(y, x, c) {
    if (y < 0 || x < 0 || x >= COLS || y >= LINES) {
        return -1; // ERR
    }
    output_map[y * (COLS + 1) + x] = c;
    return 0; // OK
}

function my_mvaddstr(y, x, str) {
    let strIdx = 0;
    while (x < 0) {
        if (strIdx >= str.length) return -1; // ERR
        x++;
        strIdx++;
    }
    while (strIdx < str.length) {
        addchModify(y, x, str[strIdx]);
        strIdx++;
        x++;
    }
    return 0; // OK
}

function option(char) {
    switch (char) {
        case 'l': LOGO += 1; break;
        case 'a': ACCIDENT = 1; break;
        case 'F': FLY = 1; break;
        case 'c': C51 = 1; break;
        case 'd': DANCE = 1; break;
        case 'r': RAND = 1; break;
        default: break;
    }
}

function resetSmoke() {
    smokeS = [];
    smokeSum = 0;
}

function windowInit(c, l, arg) {
    COLS = c;
    LINES = l;

    ACCIDENT = 0;
    LOGO = 0;
    FLY = 0;
    C51 = 0;
    DANCE = 0;
    RAND = 0;

    for (let i = 0; i < arg.length; i++) {
        if (arg[i] === '-') {
            let j = i + 1;
            while (j < arg.length && arg[j] !== '-') {
                option(arg[j]);
                j++;
            }
            i = j - 1;
        }
    }

    if (RAND === 1) {
        ACCIDENT |= Math.random() < 0.5 ? 1 : 0;
        LOGO     |= Math.random() < 0.5 ? 1 : 0;
        FLY      |= Math.random() < 0.5 ? 1 : 0;
        C51      |= Math.random() < 0.5 ? 1 : 0;
        DANCE    |= Math.random() < 0.5 ? 1 : 0;
    }

    N = -count() + COLS - 1;

    // Allocate & initialize output_map
    output_map = new Array(LINES * (COLS + 1));
    for (let i = 0; i < output_map.length; i++) {
        output_map[i] = ' ';
    }
    for (let r = 0; r < LINES; r++) {
        output_map[r * (COLS + 1) + COLS] = '\n';
    }
    output_map[LINES * (COLS + 1) - 1] = '\0';

    resetSmoke();
}

function windowDestroy() {
    resetSmoke();
    output_map = [];
}

function getOutputMapString() {
    // Exclude the terminating null byte at the end of output_map
    return output_map.slice(0, LINES * (COLS + 1) - 1).join('');
}

// --- Smoke Particle Processing ---

function add_smoke(y, x) {
    if (x % 4 === 0) {
        for (let i = 0; i < smokeSum; ++i) {
            my_mvaddstr(smokeS[i].y, smokeS[i].x, Eraser[smokeS[i].ptrn]);
            smokeS[i].y -= dy[smokeS[i].ptrn];
            smokeS[i].x += dx[smokeS[i].ptrn];
            smokeS[i].ptrn += (smokeS[i].ptrn < SMOKEPTNS - 1) ? 1 : 0;
            my_mvaddstr(smokeS[i].y, smokeS[i].x, Smoke[smokeS[i].kind][smokeS[i].ptrn]);
        }
        my_mvaddstr(y, x, Smoke[smokeSum % 2][0]);
        smokeS[smokeSum] = {
            y: y,
            x: x,
            ptrn: 0,
            kind: smokeSum % 2
        };
        smokeSum++;
    }
}

// --- Characters/Dancers drawing ---

function add_man(y, x) {
    for (let i = 0; i < 2; ++i) {
        let patternIdx = c_div(LOGOLENGTH + x, 12);
        patternIdx = c_mod(patternIdx, 2);
        my_mvaddstr(y + i, x, man[patternIdx][i]);
    }
}

function add_fdancer(y, x) {
    for (let i = 0; i < 3; ++i) {
        let patternIdx = c_div(LOGOLENGTH + x, 12);
        patternIdx = c_mod(patternIdx, 2);
        my_mvaddstr(y + i, x + 1, Efdancer[patternIdx][i]);
        my_mvaddstr(y + i, x, fdancer[patternIdx][i]);
    }
}

function add_mdancer(y, x) {
    for (let i = 0; i < 3; ++i) {
        let patternIdx = c_div(LOGOLENGTH + x, 12);
        patternIdx = c_mod(patternIdx, 3);
        my_mvaddstr(y + i, x + 1, Emdancer[patternIdx][i]);
        my_mvaddstr(y + i, x, mdancer[patternIdx][i]);
    }
}

// --- Locomotive Specific Drawings ---

function add_sl(x) {
    const sl = [
        [LOGO1, LOGO2, LOGO3, LOGO4, LWHL11, LWHL12, DELLN],
        [LOGO1, LOGO2, LOGO3, LOGO4, LWHL21, LWHL22, DELLN],
        [LOGO1, LOGO2, LOGO3, LOGO4, LWHL31, LWHL32, DELLN],
        [LOGO1, LOGO2, LOGO3, LOGO4, LWHL41, LWHL42, DELLN],
        [LOGO1, LOGO2, LOGO3, LOGO4, LWHL51, LWHL52, DELLN],
        [LOGO1, LOGO2, LOGO3, LOGO4, LWHL61, LWHL62, DELLN]
    ];
    const coal = [LCOAL1, LCOAL2, LCOAL3, LCOAL4, LCOAL5, LCOAL6, DELLN];
    const car = [LCAR1, LCAR2, LCAR3, LCAR4, LCAR5, LCAR6, DELLN];

    let py1 = 0, py2 = 0, py3 = 0, offset = 21, yoffset = 0;
    let y = (LINES / 2 - 3) | 0;

    if (FLY === 1) {
        y = c_div(x, 6) + LINES - c_div(COLS, 6) - LOGOHEIGHT;
        py1 = 2; py2 = 4; py3 = 6;
    }

    for (let i = 0; i <= LOGOHEIGHT; ++i) {
        let patternIdx = c_div(LOGOLENGTH + offset * (LOGO - 1) + x, 3);
        patternIdx = c_mod(patternIdx, LOGOPATTERNS);

        my_mvaddstr(y + i, x, sl[patternIdx][i]);
        my_mvaddstr(y + i + py1, x + 21, coal[i]);
        for (let j = 0; j <= LOGO; j++) {
            yoffset = 2 * j * FLY;
            my_mvaddstr(y + i + py3 + yoffset, x + 42 + offset * j, car[i]);
        }
    }

    if (ACCIDENT === 1) {
        add_man(y + 1, x + 14);
        yoffset = 0;
        for (let j = 0; j <= LOGO; j++) {
            yoffset = FLY * (2 + 2 * j);
            add_man(y + 1 + py2 + yoffset, x + 45 + offset * j);
            add_man(y + 1 + py2 + yoffset, x + 53 + offset * j);
        }
    }

    if (DANCE === 1 && ACCIDENT === 0 && FLY === 0) {
        add_mdancer(y - 2, x + 21);
        for (let j = 0; j <= LOGO; j++) {
            add_mdancer(y + py2 - 2, x + 45 + offset * j);
            add_mdancer(y + py2 - 2, x + 50 + offset * j);
            add_mdancer(y + py2 - 2, x + 55 + offset * j);
        }
    }

    add_smoke(y - 1, x + LOGOFUNNEL);
    return 0; // OK
}

function add_D51(x) {
    const d51 = [
        [D51STR1, D51STR2, D51STR3, D51STR4, D51STR5, D51STR6, D51STR7, D51WHL11, D51WHL12, D51WHL13, D51DEL],
        [D51STR1, D51STR2, D51STR3, D51STR4, D51STR5, D51STR6, D51STR7, D51WHL21, D51WHL22, D51WHL23, D51DEL],
        [D51STR1, D51STR2, D51STR3, D51STR4, D51STR5, D51STR6, D51STR7, D51WHL31, D51WHL32, D51WHL33, D51DEL],
        [D51STR1, D51STR2, D51STR3, D51STR4, D51STR5, D51STR6, D51STR7, D51WHL41, D51WHL42, D51WHL43, D51DEL],
        [D51STR1, D51STR2, D51STR3, D51STR4, D51STR5, D51STR6, D51STR7, D51WHL51, D51WHL52, D51WHL53, D51DEL],
        [D51STR1, D51STR2, D51STR3, D51STR4, D51STR5, D51STR6, D51STR7, D51WHL61, D51WHL62, D51WHL63, D51DEL]
    ];
    const coal = [COAL01, COAL02, COAL03, COAL04, COAL05, COAL06, COAL07, COAL08, COAL09, COAL10, COALDEL];

    let dy = 0;
    let y = (LINES / 2 - 5) | 0;

    if (FLY === 1) {
        y = c_div(x, 7) + LINES - c_div(COLS, 7) - D51HEIGHT;
        dy = 1;
    }

    for (let i = 0; i <= D51HEIGHT; ++i) {
        let patternIdx = c_mod(D51LENGTH + x, D51PATTERNS);
        my_mvaddstr(y + i, x, d51[patternIdx][i]);
        my_mvaddstr(y + i + dy, x + 53, coal[i]);
    }

    if (ACCIDENT === 1) {
        add_man(y + 2, x + 43);
        add_man(y + 2, x + 47);
    }

    if (DANCE === 1 && ACCIDENT === 0 && FLY === 0) {
        add_mdancer(y - 2, x + 43);
        add_fdancer(y - 2, x + 48);
    }

    add_smoke(y - 1, x + D51FUNNEL);
    return 0; // OK
}

function add_C51(x) {
    const c51 = [
        [C51STR1, C51STR2, C51STR3, C51STR4, C51STR5, C51STR6, C51STR7, C51WH11, C51WH12, C51WH13, C51WH14, C51DEL],
        [C51STR1, C51STR2, C51STR3, C51STR4, C51STR5, C51STR6, C51STR7, C51WH21, C51WH22, C51WH23, C51WH24, C51DEL],
        [C51STR1, C51STR2, C51STR3, C51STR4, C51STR5, C51STR6, C51STR7, C51WH31, C51WH32, C51WH33, C51WH34, C51DEL],
        [C51STR1, C51STR2, C51STR3, C51STR4, C51STR5, C51STR6, C51STR7, C51WH41, C51WH42, C51WH43, C51WH44, C51DEL],
        [C51STR1, C51STR2, C51STR3, C51STR4, C51STR5, C51STR6, C51STR7, C51WH51, C51WH52, C51WH53, C51WH54, C51DEL],
        [C51STR1, C51STR2, C51STR3, C51STR4, C51STR5, C51STR6, C51STR7, C51WH61, C51WH62, C51WH63, C51WH64, C51DEL]
    ];
    const coal = [COALDEL, COAL01, COAL02, COAL03, COAL04, COAL05, COAL06, COAL07, COAL08, COAL09, COAL10, COALDEL];

    let dy = 0;
    let y = (LINES / 2 - 5) | 0;

    if (FLY === 1) {
        y = c_div(x, 7) + LINES - c_div(COLS, 7) - C51HEIGHT;
        dy = 1;
    }

    for (let i = 0; i <= C51HEIGHT; ++i) {
        let patternIdx = c_mod(C51LENGTH + x, C51PATTERNS);
        my_mvaddstr(y + i, x, c51[patternIdx][i]);
        my_mvaddstr(y + i + dy, x + 55, coal[i]);
    }

    if (ACCIDENT === 1) {
        add_man(y + 3, x + 45);
        add_man(y + 3, x + 49);
    }

    if (DANCE === 1 && ACCIDENT === 0 && FLY === 0) {
        add_mdancer(y - 1, x + 45);
        add_fdancer(y - 1, x + 50);
    }

    add_smoke(y - 1, x + C51FUNNEL);
    return 0; // OK
}

function mapModify(mod) {
    let x = -mod + COLS - 1;
    if (LOGO >= 1) {
        add_sl(x);
    } else if (C51 === 1) {
        add_C51(x);
    } else {
        add_D51(x);
    }
}

// --- Main CLI Execution ---

async function main() {
    let rows = 24;
    let columns = 80;

    // Get terminal size
    try {
        const size = child_process.execSync('stty size', { stdio: ['inherit', 'pipe', 'ignore'] }).toString().trim().split(/\s+/);
        if (size.length === 2) {
            rows = parseInt(size[0], 10);
            columns = parseInt(size[1], 10);
        }
    } catch (e) {
        if (process.stdout.rows && process.stdout.columns) {
            rows = process.stdout.rows;
            columns = process.stdout.columns;
        }
    }

    // Merge arguments into a single string for parsing flags
    let argStr = "";
    for (let i = 2; i < process.argv.length; i++) {
        argStr += process.argv[i] + " ";
    }

    windowInit(columns, rows, argStr);

    for (let step = 0; step < N; step++) {
        mapModify(step);
        const frame = getOutputMapString();
        process.stdout.write(frame + '\n');
        await new Promise(resolve => setTimeout(resolve, 40));
    }

    windowDestroy();
}

main();
