// css file
import './App.css';
import 'utk/style.css'
import 'font-awesome/css/font-awesome.min.css'

import { BrowserRouter } from 'react-router-dom'
import Routes from './routes/Routes'

// ======================================================================================

function App() {
  return (
    <BrowserRouter>
      <div className='App'>
        <Routes/>
      </div>
  </BrowserRouter>
  );
}

export default App;

