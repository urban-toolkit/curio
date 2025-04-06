import axios from "axios"
// import paths from "./consts/route-paths"


export default axios.create({
    // baseURL: paths.baseUrl,
    baseURL: "http://localhost:5001",
    headers: {
        "Content-type": "application/json"
    }
})