#version 300 es

uniform sampler2D uColorMap;

in highp vec2 texCoords;
in lowp float filtered;
in lowp float vColorOrPicked;

out highp vec4 fragColor;

void main() {  

  if(filtered <= 0.5){
    fragColor = vec4(0.5, 0.5, 0.5, 0.7);
  }else{

    if(vColorOrPicked > 0.5){
      fragColor = vec4(0,0,1,1);
    }else{
      fragColor = vec4(texture(uColorMap, texCoords).rgb, 1.0);
    }
  }

}