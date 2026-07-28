#include <iostream>
#include <cmath>
#include <vector>
#include <string>
#include <algorithm>
#include <cstdio>

// Define functions for calculating sine and cosine
double calculateSin(double x) {
    return std::sin(x);
}

double calculateCos(double x) {
    return std::cos(x);
}

// Define function for drawing the donut
void drawDonut() {
    // Initialize variables
    double angle1 = 0.0;
    double angle2 = 0.0;
    std::vector<double> zBuffer(1760, 0.0);
    std::vector<char> pixels(1760, ' ');

    // Clear the console
    std::printf("\x1b[2J");

    const std::string chars = ".,-~:;=!*#$@";

    bool running = true;
    while (running) {
        // Clear the pixel and zBuffer lists
        std::fill(pixels.begin(), pixels.end(), ' ');
        std::fill(zBuffer.begin(), zBuffer.end(), 0.0);

        // Calculate the position and brightness of each pixel
        for (int j = 0; j < 628; j += 7) {
            for (int i = 0; i < 628; i += 2) {
                double sin_i = calculateSin(i / 100.0);
                double cos_j = calculateCos(j / 100.0);
                double sin_angle1 = calculateSin(angle1);
                double sin_j = calculateSin(j / 100.0);
                double cos_angle1 = calculateCos(angle1);
                double height = cos_j + 2;
                double distance = 1.0 / (sin_i * height * sin_angle1 + sin_j * cos_angle1 + 5.0);
                double cos_i = calculateCos(i / 100.0);
                double cos_angle2 = calculateCos(angle2);
                double sin_angle2 = calculateSin(angle2);
                double sin_height = sin_i * height * cos_angle1 - sin_j * sin_angle1;

                int x = static_cast<int>(40 + 30 * distance * (cos_i * height * cos_angle2 - sin_height * sin_angle2));
                int y = static_cast<int>(12 + 15 * distance * (cos_i * height * sin_angle2 + sin_height * cos_angle2));
                int index = x + 80 * y;

                int brightness = static_cast<int>(8 * ((sin_j * sin_angle1 - sin_i * cos_j * cos_angle1) * cos_angle2 - sin_i * cos_j * sin_angle1 - sin_j * cos_angle1 - cos_i * cos_j * sin_angle2));

                if (0 <= y && y < 22 && 0 <= x && x < 80 && distance > zBuffer[index]) {
                    zBuffer[index] = distance;
                    int b = brightness > 0 ? brightness : 0;
                    pixels[index] = static_cast<size_t>(b) < chars.length() ? chars[b] : chars.back();
                }
            }
        }

        // Print the pixels to the console
        std::printf("\x1b[H");
        for (int k = 0; k < 1760; ++k) {
            std::putchar(pixels[k]);
        }
        std::fflush(stdout);

        // Update the angles for the next iteration
        angle1 += 0.30;
        angle2 += 0.15;
    }
}

int main() {
    drawDonut();
    return 0;
}
