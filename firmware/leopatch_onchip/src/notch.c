#include <math.h>

#include "notch.h"

void notch_init(struct notch *n, float f0, float fs, float q, float start)
{
	float w0 = 2.0f * 3.14159265f * f0 / fs;
	float alpha = sinf(w0) / (2.0f * q);
	float a0 = 1.0f + alpha;

	n->b0 = 1.0f / a0;
	n->b1 = -2.0f * cosf(w0) / a0;
	n->b2 = 1.0f / a0;
	n->a1 = n->b1;
	n->a2 = (1.0f - alpha) / a0;
	n->x1 = n->x2 = n->y1 = n->y2 = start;
}

float notch_step(struct notch *n, float x)
{
	float y = n->b0 * x + n->b1 * n->x1 + n->b2 * n->x2 - n->a1 * n->y1 - n->a2 * n->y2;

	n->x2 = n->x1;
	n->x1 = x;
	n->y2 = n->y1;
	n->y1 = y;
	return y;
}
