import React, { useRef, useEffect, useState } from "react";
import './View.css';
import {Row} from 'react-bootstrap';

// declaring the types of the props
type GenericFixedPlotProps = {
    id: any,
    svgId: string,
    knotsByPhysical: any,
    activeKnotPhysical: any,
    updateStatus: any
}

export const GenericFixedPlotContainer = ({
    id,
    svgId,
    knotsByPhysical,
    activeKnotPhysical,
    updateStatus
}: GenericFixedPlotProps
) =>{
    
    const [selectActiveKnotPhysical, setSelectActiveKnotPhysical] = useState<any>({}); // object that, for each physical, stores the knotId of the activated knot

    useEffect(() => {
        setSelectActiveKnotPhysical(activeKnotPhysical);
    }, [activeKnotPhysical]);

    const updateActiveKnotPhysical = (physicalId: string, knotId: string) => {
        let returnObj: any = {};
        
        for(const key of Object.keys(selectActiveKnotPhysical)){

            if(key != physicalId){
                returnObj[key] = selectActiveKnotPhysical[key];
            }else{
                returnObj[key] = knotId;
            }
        }

        setSelectActiveKnotPhysical(returnObj);
        updateStatus("broadcastChannel", {id: "GenericFixedPlotcontainer", channel: "physicalKnotActiveChannel", message: {physicalId: physicalId, knotId: knotId}});
    }   

    return(
        <React.Fragment key={id}>
            <div style={{padding: 0, width: "100%", height: "100%"}}>
                <Row className="justify-content-center" style={{height: "100%"}}>
                    <Row className="justify-content-center" style={{height: "20%", padding: 0}}>
                        {
                            (Object.keys(knotsByPhysical)).map((key: any) => {
                                return <div style={{marginTop: "30px", marginBottom: "20px", textAlign: "center"}}>
                                    <label style={{marginRight: "10px", fontWeight: "bold"}}>{key}:</label>
                                    <select style={{width: "200px"}} key={"selectKnotsByPhysical"+key} value={selectActiveKnotPhysical[key]} onChange={e => updateActiveKnotPhysical(key, e.target.value)}>
                                        {
                                            knotsByPhysical[key].map((knotId: string) => (
                                                <option value={knotId} key={"optionKnotsByPhysical"+knotId}>{knotId}</option>
                                            ))
                                        }
                                    </select>
                                </div>
                            })
                        }
                    </Row>
                    <Row style={{width: "95%", height:"75%", padding: 0, overflow: "auto"}}>
                        <div id={svgId} style={{textAlign: "center"}}>
                        </div>
                    </Row>
                </Row>
            </div>
        </React.Fragment>
    )
}