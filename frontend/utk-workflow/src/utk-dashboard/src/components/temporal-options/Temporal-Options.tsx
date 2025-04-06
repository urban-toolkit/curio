import { useState } from 'react'
import { Modal } from "react-bootstrap"
import { FieldType } from "../../types/Types"
import Intermediary from '../../intermediary/Intermediary'

interface TemporalOptionsProps {
  fields: FieldType[]
  data: any
  setData: any
}

const TemporalOptions = ({ fields, data, setData } : TemporalOptionsProps) => {

  const [isOpen, setIsOpen]     = useState(false)
  const [selected, setSelected] = useState<any[]>([])

  function handleCancel() {
    const activeOptionsKeys = Object.keys(data)
    setSelected(activeOptionsKeys)
    setIsOpen(false)
  }

  function handleOk() {

    const isEmpty = selected.length === 0

    if (isEmpty) {
      setData({})
    
    } else {
      Intermediary.getTemporalData(selected).then((response: any) => {
        setData(response.data)
      })
      .catch((e: Error) => {
        console.log(e)
      })
    }

    setIsOpen(false)
  }
  
  function renderItems() {
    return fields.map(f => {

      let keys = [...selected]

      let isChecked = keys.includes(f.key)

      function change() {
        
        if(isChecked) {
          keys = keys.filter(k => k !== f.key)
         
        } else {
          keys.push(f.key)
        }

        isChecked = !isChecked
        setSelected(keys)
      }

      return (
        <label key={`temporal-dropdown-item-label-${f.key}`} className="list-group-item">
          <input className="form-check-input me-1" type="checkbox" value="" onChange={() => change()} checked={isChecked}/>
          {f.name}
        </label>
      )
    })
  }

  return (
    <>
      <button 
        type="button" 
        className="btn btn-outline-primary btn-sm"
        onClick={() => setIsOpen(true)}>
        Select fields
      </button>
      <Modal size="sm" show={isOpen} onHide={() => setIsOpen(false)} animation={false} className="tp-btn-modal">
        <Modal.Header closeButton onClick={() => handleCancel()}>
          <Modal.Title>Fields</Modal.Title>
        </Modal.Header>
        <Modal.Body className="tp-btn-modal-body">
          <div className="list-group tp-list-group">
            {renderItems()}
          </div>
        </Modal.Body>
        <Modal.Footer>
          <button 
            type="button" 
            className="btn btn-outline-danger btn-sm"
            onClick={() => handleCancel() }>
            Cancel
          </button>
          <button 
            type="button" 
            className="btn btn-outline-primary btn-sm"
            onClick={() => handleOk()}>
            Ok
          </button>
        </Modal.Footer>
      </Modal>
    </>
  )
}

export { TemporalOptions }