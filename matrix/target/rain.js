#!/usr/bin/env node

class Matrix {
    static MATRIX_CHARS = [
        "- ", "* ", "% ", "& ", "# ", "@ ", "1 ", "2 ", "3 ", "4 ", "5 ", "6 ", "7 ", "8 ", "9 ", "0 ",
        "ア", "ィ", "イ", "ゥ", "ウ", "ェ", "エ", "ォ", "オ", "カ", "ガ", "キ", "ギ", "ク", "グ", "ケ", "ゲ", "コ",
        "ゴ", "サ", "ザ", "シ", "ジ", "ス", "ズ", "セ", "ゼ", "ソ", "ゾ", "タ", "ダ", "チ", "ヂ", "ッ", "ツ", "ヅ", "テ"
    ];
    static TERMINAL_COLOURS = ["22", "28"];

    constructor(screenWidth = 150, lineCount = 750, lineSpeed = 0.1) {
        this._screenWidth = screenWidth;
        this._lineCount = lineCount;
        this._lineSpeed = lineSpeed;
        this.lineArray = {};
    }

    _getTextColourLightGreenChar() {
        return "\x1b[38;5;15m";
    }

    _getTextColourRandomChar() {
        const randomIndex = Math.floor(Math.random() * 2);
        return "\x1b[38;5;" + Matrix.TERMINAL_COLOURS[randomIndex] + "m";
    }

    _getCharacter() {
        const total = Matrix.MATRIX_CHARS.length;
        const randomIndex = Math.floor(Math.random() * total);
        return Matrix.MATRIX_CHARS[randomIndex];
    }

    _setScreenLineArray() {
        for (let i = 0; i < this._screenWidth; i++) {
            this.lineArray[i] = 1;
        }
    }

    async startMatrix() {
        this._setScreenLineArray();
        for (let l = 0; l < this._lineCount; l++) {
            let line = "";

            for (let m = 0; m < this._screenWidth; m++) {
                const n = this.lineArray[m];
                if (n === 1 || n === 2) {
                    if (n === 2) {
                        line = line + this._getTextColourLightGreenChar() + this._getCharacter();
                        this.lineArray[m] = 1;
                    } else {
                        line = line + this._getTextColourRandomChar() + this._getCharacter();
                    }

                    if (1 === Math.floor(Math.random() * 30) + 1) {
                        this.lineArray[m] = 0;
                    }
                } else {
                    line = line + this._getTextColourRandomChar() + " ";
                    if (1 === Math.floor(Math.random() * 60) + 1) {
                        this.lineArray[m] = 2;
                    }
                }
            }

            console.log(line);
            await new Promise(resolve => setTimeout(resolve, this._lineSpeed * 1000));
        }
    }
}

if (require.main === module) {
    const matrix = new Matrix();
    matrix.startMatrix();
}
