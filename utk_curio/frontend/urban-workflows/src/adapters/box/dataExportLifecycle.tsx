import React, { useState, useEffect } from 'react';
import { BoxLifecycleHook } from '../../registry/types';
import { fetchData } from '../../services/api';
import OutputContent from '../../components/editing/OutputContent';

export const useDataExportLifecycle: BoxLifecycleHook = (data, boxState) => {
  const [downloadFormat, setDownloadFormat] = useState<string>('csv');

  const sendCodeOverride = async () => {
    boxState.setOutput({ code: 'exec', content: '', outputType: downloadFormat });
    await downloadData();
    boxState.setOutput({ code: 'success', content: 'Download complete.', outputType: downloadFormat });
  };

  const customWidgetsCallback = (div: HTMLElement) => {
    const label = document.createElement('label');
    label.setAttribute('for', 'exportFormat');
    label.style.marginRight = '5px';
    label.textContent = 'Export format: ';

    const select = document.createElement('select');
    select.setAttribute('name', 'exportFormat');
    select.setAttribute('id', data.nodeId + '_select_format');

    ['csv', 'json', 'geojson'].forEach((optionText) => {
      const option = document.createElement('option');
      option.setAttribute('value', optionText);
      option.textContent = optionText.toUpperCase();
      select.appendChild(option);
    });

    select.value = downloadFormat;
    select.addEventListener('change', (event) => {
      if (event.target) {
        const target = event.target as HTMLOptionElement;
        setDownloadFormat(target.value);
      }
    });

    div.appendChild(label);
    div.appendChild(select);
  };

  const downloadData = async () => {
    let filePath = '';
    if (data.input && typeof data.input === 'object' && data.input.path) {
      filePath = data.input.path;
    }
    if (!filePath) return;

    try {
      const result: any = await fetchData(`${filePath}`);
      let fileName = 'data_export';
      let fileContent = '';

      if (
        downloadFormat === 'csv' &&
        result.data &&
        (result.dataType === 'dataframe' || result.dataType === 'geodataframe')
      ) {
        const csvRows: string[] = [];
        if (result.dataType === 'dataframe') {
          const columns = Object.keys(result.data);
          const rows = result.data[columns[0]]?.length || 0;
          csvRows.push(columns.join(','));
          for (let i = 0; i < rows; i++) {
            const row = columns.map(col => JSON.stringify(result.data[col][i] ?? ''));
            csvRows.push(row.join(','));
          }
        } else if (result.dataType === 'geodataframe' && result.data.features) {
          const features = result.data.features;
          const properties = features.map((f: any) => ({
            ...f.properties,
            geometry: JSON.stringify(f.geometry),
          }));
          const columns = Object.keys(properties[0]);
          csvRows.push(columns.join(','));
          for (const row of properties) {
            const values = columns.map(col => JSON.stringify(row[col] ?? ''));
            csvRows.push(values.join(','));
          }
        }
        fileContent = csvRows.join('\n');
        fileName += '.csv';
      } else if (downloadFormat === 'geojson') {
        fileContent = JSON.stringify(result.data);
        fileName += '.geojson';
      } else {
        fileContent = JSON.stringify(result.data);
        fileName += '.json';
      }

      const blob = new Blob([fileContent], { type: 'text/plain;charset=utf-8' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err) {
      console.error('Failed to download data', err);
    }
  };

  useEffect(() => {
    boxState.setOutput({ code: 'success', content: '', outputType: downloadFormat });
  }, [data.input, downloadFormat]);

  const contentComponent = React.useMemo(
    () => <OutputContent output={boxState.output} />,
    [boxState.output],
  );

  return {
    sendCodeOverride,
    setSendCodeCallbackOverride: () => {},
    customWidgetsCallback,
    contentComponent,
  };
}
