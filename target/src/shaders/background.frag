#version 450
// Kept identical to GLES_BACKGROUND_FS in emugfx.c.
layout(location = 0) in vec2 uv;
layout(location = 0) out vec4 color;
layout(push_constant) uniform Push {
    float t;
} push;

void main() {
    float t = push.t;
    vec3 col = 0.5 + 0.5 * cos(t + uv.xyx * vec3(6.0, 4.0, 3.0) + vec3(0.0, 2.0, 4.0));
    float v = sin(uv.x * 20.0 + t) + sin(uv.y * 14.0 - t * 1.5) + sin((uv.x + uv.y) * 9.0 + t * 0.5);
    col *= 0.75 + 0.25 * sin(v * 3.14159265);
    color = vec4(col, 1.0);
}
