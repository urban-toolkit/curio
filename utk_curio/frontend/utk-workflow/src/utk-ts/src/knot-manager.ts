import { IExKnot, IKnot } from "./interfaces";
import { Knot } from "./knot";
import { Layer } from "./layer";

export class KnotManager {

    protected _knots: Knot[] = [];
    protected _updateStatusCallback: any;

    public init(updateStatusCallback: any){
        this._updateStatusCallback = updateStatusCallback;
        this.toggleKnot(""); // just to update the knots in the view
    }

    get knots(): Knot[] {
        return this._knots;
    }

    createKnot(id: string, physicalLayer: Layer, knotSpecification: IKnot | IExKnot, grammarInterpreter: any, visible: boolean): Knot {
        
        let knot = new Knot(id, physicalLayer, knotSpecification, grammarInterpreter, visible);
        this._knots.push(knot);
        return knot;
    }

    toggleKnot(id: string, value: boolean | null = null){

        let knotVisibility: any = {};

        for(const knot of this._knots){
            if(knot.id == id){
                if(value != null){
                    knot.visible = value;
                }else{
                    knot.visible = !knot.visible;
                }
            }
            knotVisibility[knot.id] = knot.visible;
        }

        if(this._updateStatusCallback != undefined){
            this._updateStatusCallback("knotVisibility", knotVisibility);
        }
    }

    overwriteSelectedElements(externalSelected: number[], layerId: string, viewId: number){
        for(const knot of this._knots){
            if(knot.physicalLayer.id == layerId){
                knot.overwriteSelectedElements(externalSelected, viewId);
            }
        }
    }

    getKnotById(knotId: string){
        for(const knot of this._knots){
            if(knot.id == knotId){
                return knot;
            }
        }

        return null;
    }
}
