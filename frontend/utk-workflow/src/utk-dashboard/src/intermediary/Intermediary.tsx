// import axios from 'axios'
// import paths from '../consts/route-paths'

// class Manager {

//     async getTseries(fld:string) {
//         const method = 'post'
//         const url = `${paths.baseUrl}/tseries`

//         const data = { fld }
//         const resp = await axios[method](url, data)

//         return resp.data
//     }

// }

// export default new Manager()

import { AxiosResponse } from "axios"
import http from "../http-common/http-common"
import { FieldType } from "../types/Types"

class Intermediary {

    async getFields() {
        const url = "/fields"
        const response =  await http.get<FieldType[]>(url)
        return response.data
    }

    getHmat(pt:number, time:number) {
        const url = "/hmat"
        const data = { pt, time }
        
        return http.post<any>(url, data)
    }
    
    getTemporalData(arr:object) {
        const url = "/temporalData"
        const data = { arr }
        
        return http.post<any>(url, data)
    }

    getScatter(fld1:string, fld2:string) {
        const url = "/scatter"
        const data = { fld1, fld2 }
        
        return http.post<any>(url, data)
    }
}

export default new Intermediary()