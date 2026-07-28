#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import os from 'os';
import process from 'process';

const VERSION = "2.0.0";

const Direction = {
  UP: 0,
  RIGHT: 1,
  DOWN: 2,
  LEFT: 3
};

const PIPE_SETS = [
  "┃┏ ┓┛━┓  ┗┃┛┗ ┏━",
  "│╭ ╮╯─╮  ╰│╯╰ ╭─",
  "│┌ ┐┘─┐  └│┘└ ┌─",
  "║╔ ╗╝═╗  ╚║╝╚ ╔═",
  "|+ ++-+  +|++ +-",
  "|/ \\ /-\\  \\|/\\ /-",
  ".o ....  .... .o",
  ".o oo.o  o.oo o.",
  "-\\ /\\|/  /-\\/ \\|",
  "╿┍ ┑┚╼┒  ┕╽┙┖ ┎╾"
];

function getPreparedSets() {
  const sets = [];
  for (const pipeSet of PIPE_SETS) {
    const padded = (pipeSet + " ".repeat(16)).slice(0, 16);
    for (let i = 0; i < 16; i++) {
      sets.push(padded[i]);
    }
  }
  return sets;
}

const PREPARED_SETS = getPreparedSets();

const DEFAULT_CONFIG = {
  pipes: 1,
  fps: 75,
  steady: 13,
  limit: 2000,
  random_start: false,
  bold: true,
  color: true,
  keep_style: false,
  colors: [1, 2, 3, 4, 5, 6, 7, 0],
  pipe_types: [0]
};

function getConfigPath() {
  if (process.platform === 'win32') {
    const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
    return path.join(localAppData, 'pipes-js', 'config.json');
  }
  return path.join(os.homedir(), '.config', 'pipes-js', 'config.json');
}

function loadConfig() {
  const configPath = getConfigPath();
  if (!fs.existsSync(configPath)) {
    return { ...DEFAULT_CONFIG };
  }
  try {
    const raw = fs.readFileSync(configPath, 'utf8');
    const data = JSON.parse(raw);
    return {
      pipes: typeof data.pipes === 'number' ? data.pipes : DEFAULT_CONFIG.pipes,
      fps: typeof data.fps === 'number' ? data.fps : DEFAULT_CONFIG.fps,
      steady: typeof data.steady === 'number' ? data.steady : DEFAULT_CONFIG.steady,
      limit: typeof data.limit === 'number' ? data.limit : DEFAULT_CONFIG.limit,
      random_start: typeof data.random_start === 'boolean' ? data.random_start : DEFAULT_CONFIG.random_start,
      bold: typeof data.bold === 'boolean' ? data.bold : DEFAULT_CONFIG.bold,
      color: typeof data.color === 'boolean' ? data.color : DEFAULT_CONFIG.color,
      keep_style: typeof data.keep_style === 'boolean' ? data.keep_style : DEFAULT_CONFIG.keep_style,
      colors: Array.isArray(data.colors) ? data.colors : DEFAULT_CONFIG.colors,
      pipe_types: Array.isArray(data.pipe_types) ? data.pipe_types : DEFAULT_CONFIG.pipe_types
    };
  } catch (err) {
    return { ...DEFAULT_CONFIG };
  }
}

function saveConfig(config) {
  const configPath = getConfigPath();
  try {
    fs.mkdirSync(path.dirname(configPath), { recursive: true });
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf8');
  } catch (err) {
    // Ignore save errors
  }
}

function parseArgs() {
  const args = process.argv.slice(2);
  const parsed = {
    pipes: null,
    fps: null,
    steady: null,
    limit: null,
    random: false,
    no_bold: false,
    no_color: false,
    pipe_style: null,
    keep_style: false,
    save_config: false,
    version: false,
    help: false
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '-h' || arg === '--help') {
      parsed.help = true;
    } else if (arg === '-v' || arg === '--version') {
      parsed.version = true;
    } else if (arg === '-R' || arg === '--random') {
      parsed.random = true;
    } else if (arg === '-B' || arg === '--no-bold') {
      parsed.no_bold = true;
    } else if (arg === '-C' || arg === '--no-color') {
      parsed.no_color = true;
    } else if (arg === '-K' || arg === '--keep-style') {
      parsed.keep_style = true;
    } else if (arg === '-S' || arg === '--save-config') {
      parsed.save_config = true;
    } else if (arg === '-p' || arg === '--pipes') {
      parsed.pipes = parseInt(args[++i], 10);
    } else if (arg.startsWith('--pipes=')) {
      parsed.pipes = parseInt(arg.split('=')[1], 10);
    } else if (arg === '-f' || arg === '--fps') {
      parsed.fps = parseInt(args[++i], 10);
    } else if (arg.startsWith('--fps=')) {
      parsed.fps = parseInt(arg.split('=')[1], 10);
    } else if (arg === '-s' || arg === '--steady') {
      parsed.steady = parseInt(args[++i], 10);
    } else if (arg.startsWith('--steady=')) {
      parsed.steady = parseInt(arg.split('=')[1], 10);
    } else if (arg === '-r' || arg === '--limit') {
      parsed.limit = parseInt(args[++i], 10);
    } else if (arg.startsWith('--limit=')) {
      parsed.limit = parseInt(arg.split('=')[1], 10);
    } else if (arg === '-P' || arg === '--pipe-style') {
      parsed.pipe_style = parseInt(args[++i], 10);
    } else if (arg.startsWith('--pipe-style=')) {
      parsed.pipe_style = parseInt(arg.split('=')[1], 10);
    }
  }

  return parsed;
}

function printHelp() {
  console.log(`usage: pipes [-h] [-p PIPES] [-f FPS] [-s STEADY] [-r LIMIT] [-R] [-B] [-C] [-P {0,1,2,3,4,5,6,7,8,9}] [-K] [-S] [-v]

Basically pipes.sh but rewritten in JavaScript (Node.js)

options:
  -h, --help            show this help message and exit
  -p PIPES, --pipes PIPES
                        number of pipes
  -f FPS, --fps FPS     frames per second (20-100)
  -s STEADY, --steady STEADY
                        steadiness (5-15)
  -r LIMIT, --limit LIMIT
                        character limit before reset
  -R, --random          random start
  -B, --no-bold         disable bold
  -C, --no-color        disable color
  -P {0..9}, --pipe-style {0..9}
                        change pipe style (0-9)
  -K, --keep-style      keep style on wrap
  -S, --save-config     save current settings as default
  -v, --version         show program's version number and exit`);
}

function randomInt(max) {
  return Math.floor(Math.random() * max);
}

function randomChoice(arr) {
  return arr[randomInt(arr.length)];
}

class Pipe {
  constructor(x, y, direction, pipe_type, color) {
    this.x = x;
    this.y = y;
    this.direction = direction;
    this.pipe_type = pipe_type;
    this.color = color;
  }
}

class PipesApp {
  constructor(config) {
    this.config = config;
    this.pipes = [];
    this.count = 0;
    this.running = true;
    this.width = process.stdout.columns || 80;
    this.height = process.stdout.rows || 24;

    this.initPipes();
  }

  initPipes() {
    this.pipes = [];
    for (let i = 0; i < this.config.pipes; i++) {
      const direction = this.config.random_start ? randomInt(4) : Direction.UP;
      const x = this.config.random_start ? randomInt(this.width) : Math.floor(this.width / 2);
      const y = this.config.random_start ? randomInt(this.height) : Math.floor(this.height / 2);
      const pipe_type = randomChoice(this.config.pipe_types);
      const color = randomChoice(this.config.colors);

      this.pipes.push(new Pipe(x, y, direction, pipe_type, color));
    }
  }

  getAnsiColorAttr(color) {
    if (!this.config.color) {
      return this.config.bold ? '\x1b[1m' : '\x1b[0m';
    }
    const colorCode = 30 + (color % 8);
    return this.config.bold ? `\x1b[1;${colorCode}m` : `\x1b[0;${colorCode}m`;
  }

  drawPipe(pipe, oldDirection, newDirection) {
    const base = pipe.pipe_type * 16;
    const index = base + oldDirection * 4 + newDirection;
    const char = index < PREPARED_SETS.length ? PREPARED_SETS[index] : '?';
    const attr = this.getAnsiColorAttr(pipe.color);

    // ANSI escape: 1-indexed row, col
    const r = pipe.y + 1;
    const c = pipe.x + 1;
    process.stdout.write(`\x1b[${r};${c}H${attr}${char}\x1b[0m`);
  }

  clearScreen() {
    process.stdout.write('\x1b[2J\x1b[H');
  }

  update() {
    if (!this.running) return;

    // Check resized terminal
    const currentW = process.stdout.columns || 80;
    const currentH = process.stdout.rows || 24;
    if (currentW !== this.width || currentH !== this.height) {
      this.width = currentW;
      this.height = currentH;
      this.clearScreen();
    }

    for (const pipe of this.pipes) {
      let x = pipe.x;
      let y = pipe.y;
      const oldDirection = pipe.direction;

      if (oldDirection % 2 !== 0) { // RIGHT (1) or LEFT (3)
        x += -oldDirection + 2;
      } else { // UP (0) or DOWN (2)
        y += oldDirection - 1;
      }

      // Handle wrapping
      if (x < 0 || x >= this.width || y < 0 || y >= this.height) {
        if (!this.config.keep_style) {
          pipe.pipe_type = randomChoice(this.config.pipe_types);
          pipe.color = randomChoice(this.config.colors);
        }
        x = (x % this.width + this.width) % this.width;
        y = (y % this.height + this.height) % this.height;
      }

      let newDirection = oldDirection;
      if (randomInt(this.config.steady) <= 1) {
        const turn = Math.random() < 0.5 ? -1 : 1;
        newDirection = (oldDirection + turn + 4) % 4;
      }

      this.drawPipe(pipe, oldDirection, newDirection);

      pipe.x = x;
      pipe.y = y;
      pipe.direction = newDirection;
    }

    this.count += this.pipes.length;
    if (this.config.limit > 0 && this.count >= this.config.limit) {
      this.clearScreen();
      this.count = 0;
    }
  }

  handleKey(keyStr) {
    const keyChar = keyStr.toUpperCase();
    if (keyChar === 'P' && this.config.steady < 15) {
      this.config.steady++;
    } else if (keyChar === 'O' && this.config.steady > 3) {
      this.config.steady--;
    } else if (keyChar === 'F' && this.config.fps < 100) {
      this.config.fps++;
    } else if (keyChar === 'D' && this.config.fps > 20) {
      this.config.fps--;
    } else if (keyChar === 'B') {
      this.config.bold = !this.config.bold;
    } else if (keyChar === 'C') {
      this.config.color = !this.config.color;
    } else if (keyChar === 'K') {
      this.config.keep_style = !this.config.keep_style;
    } else if (keyChar === '?' || keyStr === '\x1b') { // ESC or ?
      this.stop();
    }
  }

  stop() {
    this.running = false;
    this.cleanup();
    process.exit(0);
  }

  cleanup() {
    process.stdout.write('\x1b[?25h\x1b[0m\x1b[2J\x1b[H');
    if (process.stdin.isTTY) {
      try {
        process.stdin.setRawMode(false);
      } catch (e) {}
    }
  }

  start() {
    // Hide cursor & clear screen
    process.stdout.write('\x1b[?25l');
    this.clearScreen();

    // Raw mode input
    if (process.stdin.isTTY) {
      process.stdin.setRawMode(true);
      process.stdin.resume();
      process.stdin.setEncoding('utf8');
      process.stdin.on('data', (key) => {
        if (key === '\x03') { // Ctrl+C
          this.stop();
        } else {
          this.handleKey(key);
        }
      });
    }

    const cleanup = () => this.cleanup();
    process.on('SIGINT', cleanup);
    process.on('SIGTERM', cleanup);
    process.on('exit', cleanup);

    const loop = () => {
      if (!this.running) return;
      this.update();
      const delay = Math.max(1, Math.floor(1000 / this.config.fps));
      setTimeout(loop, delay);
    };

    loop();
  }
}

function main() {
  const cliArgs = parseArgs();

  if (cliArgs.help) {
    printHelp();
    process.exit(0);
  }

  if (cliArgs.version) {
    console.log(`pipes-js v${VERSION}`);
    process.exit(0);
  }

  const config = loadConfig();

  if (cliArgs.pipes !== null && !isNaN(cliArgs.pipes)) {
    config.pipes = Math.max(1, cliArgs.pipes);
  }
  if (cliArgs.fps !== null && !isNaN(cliArgs.fps)) {
    config.fps = Math.max(20, Math.min(100, cliArgs.fps));
  }
  if (cliArgs.steady !== null && !isNaN(cliArgs.steady)) {
    config.steady = Math.max(5, Math.min(15, cliArgs.steady));
  }
  if (cliArgs.limit !== null && !isNaN(cliArgs.limit)) {
    config.limit = Math.max(0, cliArgs.limit);
  }
  if (cliArgs.random) {
    config.random_start = true;
  }
  if (cliArgs.no_bold) {
    config.bold = false;
  }
  if (cliArgs.no_color) {
    config.color = false;
  }
  if (cliArgs.keep_style) {
    config.keep_style = true;
  }
  if (cliArgs.pipe_style !== null && !isNaN(cliArgs.pipe_style) && cliArgs.pipe_style >= 0 && cliArgs.pipe_style <= 9) {
    config.pipe_types = [cliArgs.pipe_style];
  }

  if (cliArgs.save_config) {
    saveConfig(config);
  }

  const app = new PipesApp(config);
  app.start();
}

main();
