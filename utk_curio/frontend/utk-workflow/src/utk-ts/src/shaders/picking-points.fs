#version 300 es

in highp vec4 idColors;
out highp vec4 fragColor;

void main() {
    // fragColor = vec4(idColors[0]/57.0,0,0,1);
    // fragColor = vec4(1,0,0,1);
    fragColor =  idColors;
}