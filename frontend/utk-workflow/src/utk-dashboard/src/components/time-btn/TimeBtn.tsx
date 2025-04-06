import "./TimeBtn.css"

import Button from 'react-bootstrap/Button'
import ButtonGroup from 'react-bootstrap/ButtonGroup'

interface TimeBtnProps {
  activeTime: number
  nTimes: number
  setTime: (time:number) => void
}

const TimeBtn = ({ activeTime, nTimes, setTime } : TimeBtnProps) => {
  // console.log("TimeBtn")
  const handleMinusClick = () => {
    const newTime = activeTime - 1
    if(newTime >= 0) setTime(newTime)
  
  }

  const handlePlusClick = () => {
    const newTime = activeTime + 1
    if(newTime <= nTimes - 1) setTime(newTime)

  }

  return (
      <ButtonGroup aria-label="Basic example" size="sm">
        <Button variant="outline-primary" onClick={() => handleMinusClick()}>-1</Button>
        <Button variant="outline-primary">{activeTime}h</Button>
        <Button variant="outline-primary" onClick={() => handlePlusClick()}>+1</Button>
      </ButtonGroup>
    // <div className='btn-group btn-group-sm time-btn-group' role='group'>
    //   <button 
    //     type='button' 
    //     className='btn time-btn' 
    //     data-bs-toggle="popover" title={"popMinus"}
    //     onClick={() => handleMinusClick()}>-1</button>
    //     {/* // onClick={() => console.log("-1")}>-1</button> */}

    //   <div 
    //     className="d-inline time-label"
    //     data-bs-toggle="popover" title={"popTime"}
    //     >{activeTime}h
    //     </div> 
      
    //   <button 
    //     type='button' 
    //     className='btn time-btn' 
    //     data-bs-toggle="popover" title={"popPlus"}
    //     onClick={() => handlePlusClick()}>+1</button>
    // </div>
  )
}

export { TimeBtn }