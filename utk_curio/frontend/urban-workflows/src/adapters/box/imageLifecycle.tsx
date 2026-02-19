import React, { useState, useEffect, useRef } from 'react';
import { BoxLifecycleHook } from '../../registry/types';
import { BoxType, VisInteractionType } from '../../constants';
import { useProvenanceContext } from '../../providers/ProvenanceProvider';
import { useFlowContext } from '../../providers/FlowProvider';
import { fetchData } from '../../services/api';
import { formatDate, mapTypes } from '../../utils/formatters';
import ImageGrid from './components/ImageGrid';

export const useImageLifecycle: BoxLifecycleHook = (data, boxState) => {
  const [interactions, _setInteractions] = useState<any>({});
  const interactionsRef = React.useRef(interactions);
  const setInteractions = (newData: any) => {
    interactionsRef.current = newData;
    _setInteractions(newData);
  };

  const dataInputBypass = useRef(false);
  const [images, setImages] = useState<string[]>([]);
  const [interacted, setInteracted] = useState<string[]>([]);

  const { boxExecProv } = useProvenanceContext();
  const { workflowNameRef } = useFlowContext();

  useEffect(() => {
    const loadImageData = async () => {
      if (data.input && dataInputBypass.current) {
        const startTime = formatDate(new Date());
        const typesInput = [data.input.dataType];
        const typesOutput = [...typesInput];

        boxExecProv(
          startTime,
          startTime,
          workflowNameRef.current,
          BoxType.VIS_IMAGE + '-' + data.nodeId,
          mapTypes(typesInput),
          mapTypes(typesOutput),
          '',
        );

        let parsedInput = data.input;

        if (parsedInput.path) {
          try {
            parsedInput = await fetchData(parsedInput.path);
          } catch (err) {
            console.error('Failed to fetch image data:', err);
            alert('Error fetching image data. Please try again.');
            return;
          }
        }

        if (
          parsedInput.dataType !== 'dataframe' ||
          !parsedInput.data?.image_id ||
          !parsedInput.data?.image_content
        ) {
          alert("Image needs a DataFrame with 'image_id' and 'image_content' columns.");
          dataInputBypass.current = true;
          return;
        }

        const newImages: string[] = [];
        const newInteracted: string[] = [];

        for (const key of Object.keys(parsedInput.data.image_content)) {
          let iterator: string[] = [];

          if (Array.isArray(parsedInput.data.image_content[key])) {
            iterator = [...parsedInput.data.image_content[key]];
          } else {
            iterator = [parsedInput.data.image_content[key]];
          }

          for (const base64ImageContent of iterator) {
            if (parsedInput.data.interacted != undefined) {
              newInteracted.push(parsedInput.data.interacted[key]);
            } else {
              newInteracted.push('0');
            }
            newImages.push('data:image/png;base64,' + base64ImageContent);
          }
        }

        setImages(newImages);
        setInteracted(newInteracted);
        boxState.setOutput({ code: 'success', content: data.input });
        data.outputCallback(data.nodeId, data.input);
      }

      dataInputBypass.current = true;
    };

    loadImageData();
  }, [data.input]);

  const clickImage = (index: number) => {
    const newObj: any = {};
    newObj['images_click'] = {
      type: VisInteractionType.POINT,
      data: [index],
      priority: 1,
      source: BoxType.VIS_IMAGE,
    };
    setInteractions(newObj);
  };

  useEffect(() => {
    data.interactionsCallback(interactions, data.nodeId);
  }, [interactions]);

  const contentComponent = (
    <ImageGrid
      nodeId={data.nodeId}
      images={images}
      interacted={interacted}
      onClickImage={clickImage}
    />
  );

  return {
    contentComponent,
    setSendCodeCallbackOverride: (_: any) => {},
  };
}
