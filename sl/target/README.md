# Steam Locomotive - JavaScript Port

A JavaScript (Node.js) port of the classic `sl` (Steam Locomotive) program.

## Prerequisites

- Node.js v12.x or higher

## Build

No build step is required (interpreted JavaScript).

## Run

Run the animation directly with:

```bash
node target/sl.js
```

### Options

The port supports all original options:

- `-a`: Accident mode (people crying for help)
- `-F`: Fly mode (locomotive flies up)
- `-c`: C51 locomotive mode (different steam engine)
- `-l`: Logo locomotive mode (longer train with cars, multiple `-l` adds more cars)
- `-d`: Dance mode (dancers appear above the train)
- `-r`: Random mode (randomly applies the options above)

Examples:

```bash
node target/sl.js -a
node target/sl.js -F
node target/sl.js -l -l
node target/sl.js -d
```
