import React, { useEffect, useState } from 'react';
import { useCode } from '../hook/useCode';

type ProjectListProps = {
  onSelectProject: (projectName: string) => void;
};

const ProjectList: React.FC<ProjectListProps> = ({ onSelectProject }) => {
  const [projectNames, setProjectNames] = useState<string[]>([]);
  const [previousProject, setPreviousProject] = useState("");
  const [selectedProject, setSelectedProject] = useState<string>("");
  const { createCodeNode } = useCode();

  useEffect(() => {
    // Obter lista de nomes de projetos
    fetch('http://localhost:5002/getAllProjectNames')
      .then(response => response.json())
      .then(data => {setProjectNames(data)})
      .catch(error => console.error("Erro ao carregar projetos:", error));
  }, []);

  const handleSelectChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const selected = event.target.value;
    setSelectedProject(selected);
    onSelectProject(selected);
  };

  // useEffect(() => {
  //   if (selectedProject && selectedProject !== previousProject) {
  //     fetch(`http://localhost:5002/getProjectItems?name=${selectedProject}`)
  //       .then(async (response) => {
  //         if (!response.ok) {
  //           throw new Error('response was not ok');
  //         }
  //         return response.json();
  //       })
  //       .then((projects) => {
  //         projects.forEach((project) => {
  //           createCodeNode(project.boxType, null, true, project.id);
  //         });
  //       })
  //       .catch((error) => {
  //         console.error('Error fetching project items:', error);
  //       });

  //     setPreviousProject(selectedProject);
  //   }
  // }, [selectedProject, previousProject]);

  return (
    <div style={{ position: 'relative', zIndex: 10, padding: '10px', background: 'white', borderRadius: '8px', boxShadow: '0px 4px 8px rgba(0,0,0,0.1)' }}>
      <label htmlFor="projectSelect">Select a project:</label>
      <select
        id="projectSelect"
        value={selectedProject}
        onChange={handleSelectChange}
        style={{ width: '100%', padding: '8px', marginTop: '5px', borderRadius: '4px' }}
      >
        <option value=""></option>
        {projectNames.map((name, index) => (
          <option key={index} value={name}>
            {name}
          </option>
        ))}
      </select>
    </div>
  );
};

export default ProjectList;
