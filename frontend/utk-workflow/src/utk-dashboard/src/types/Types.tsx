export interface FieldType {
    colorRange: [string, string]
    key: string
    name: string
    nick: string
    tsSelected: boolean
    unit: string
}

export interface TimeSeriesEntry {
    c: string
    f: string
    t: number | null
    v: number | null
} 