import { Routes, Route } from 'react-router-dom'
import { Home } from '../views/home'

function MyRoutes() {
  return(
    <Routes>
      <Route path='/' element={<Home/>} />
    </Routes>
  )
}

export default MyRoutes