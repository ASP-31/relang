# Donut (C++ Port)

ASCII art rotating donut animation ported from Python to C++.

## Prerequisites

To compile the C++ source code, you need a C++17 compliant compiler installed:
- **Linux**: GCC `g++` or Clang `clang++`.
- **Windows**: MinGW-w64 (`g++`) or MSVC (`cl.exe`).

---

## Linux/macOS Compilation and Run

### 1. Build
Compile the code with optimization flags (`-O3`) for smooth rendering performance:
```bash
g++ -O3 target/donut.cpp -o target/donut
```

### 2. Run
Execute the compiled binary:
```bash
./target/donut
```

---

## Windows Compilation and Run

Depending on which compiler you have installed on Windows, follow one of the methods below:

### Method A: Using MinGW (`g++`)

If `g++.exe` is installed (e.g. at `C:\MinGW\bin\g++.exe` or `C:\msys64\mingw64\bin\g++.exe`) but not added to your system path:

1. **Open PowerShell** in the project directory.
2. **Add MinGW bin directory to PATH** (so it can find the compiler and dependent DLLs):
   ```powershell
   $env:PATH = "C:\MinGW\bin;" + $env:PATH
   ```
3. **Compile**:
   ```powershell
   g++ -O3 target/donut.cpp -o target/donut.exe
   ```
4. **Run**:
   ```powershell
   .\target\donut.exe
   ```

### Method B: Using MSVC (`cl.exe`)

1. Open the **Developer Command Prompt for Visual Studio**.
2. Navigate to the project root directory.
3. **Compile**:
   ```cmd
   cl /EHsc /O2 target\donut.cpp /Fe:target\donut.exe
   ```
4. **Run**:
   ```cmd
   target\donut.exe
   ```

---

## Verification

Since this is an Easy project, validation is volunteer-verified. You can demonstrate the working C++ animation program in your terminal.
To test it, verify that it clears the terminal screen and displays the rotating donut shape spinning continuously.
