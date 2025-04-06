import React from 'react'
import './Nav.css'

function Nav(props:any) {
  return (
    <React.Fragment>
      <aside className="menu-area">
        <nav className="menu">
          <div className="res">
            <div className="form">
              {/* <div className="row g-3 p-1 align-items-center"> */}
              <div className="row align-items-center">
                {props.children}
              </div>
              </div>
          </div>
        </nav>
      </aside>
    </React.Fragment>
  )
}

export { Nav }