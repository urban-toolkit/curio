import React from 'react';
import CSS from 'csstype';

interface ImageGridProps {
  nodeId: string;
  images: string[];
  interacted: string[];
  onClickImage: (index: number) => void;
}

const containerStyle: CSS.Properties = {
  display: 'flex',
  flexWrap: 'wrap',
  maxHeight: '100%',
  maxWidth: '100%',
  overflowY: 'auto',
};

const imageStyle: CSS.Properties = { height: 'auto', margin: '5px' };
const selectedImageStyle: CSS.Properties = { height: 'auto', margin: '5px', border: '3px solid red' };

export default function ImageGrid({ nodeId, images, interacted, onClickImage }: ImageGridProps) {
  return (
    <div className="nowheel nodrag" id={`imageBox_content_${nodeId}`} style={containerStyle}>
      {images.map((src, index) => {
        const isSelected =
          interacted != null &&
          interacted.length === images.length &&
          interacted[index] === '1';

        return (
          <div key={index} id={`imageBox_content_${nodeId}_${index}`}>
            <img
              src={src}
              width={50}
              height={50}
              style={isSelected ? selectedImageStyle : imageStyle}
              onClick={() => onClickImage(index)}
            />
          </div>
        );
      })}
    </div>
  );
}
