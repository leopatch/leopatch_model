/*
 * Mains hum removal: second-order notch filters (RBJ audio EQ cookbook), direct form I.
 */
#pragma once

struct notch {
	float b0, b1, b2, a1, a2;
	float x1, x2, y1, y2;
};

/* Notch at f0 Hz for a signal sampled at fs Hz, settled at the value start (DC passes). */
void notch_init(struct notch *n, float f0, float fs, float q, float start);

float notch_step(struct notch *n, float x);
