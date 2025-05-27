
import React, { useState, useEffect, useRef } from "react";
import { Form } from "react-bootstrap";

type SearchWidgetProps = {
  obj: any // map 
  inputId: string
  viewId: string
}

export const SearchWidget = ({obj, inputId, viewId}:SearchWidgetProps) =>{

    return(
      <React.Fragment>
        <input type="text" size={24} className={inputId} name="searchBar" placeholder='Search place'></input>
      </React.Fragment>
    )
}




