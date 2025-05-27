export class KeyEvents {
    // div to attach the events
    private _map: any;

    setMap(map: any): void {
        this._map = map;
    }

    bindEvents(): void {
        // this._map.canvas.removeEventListener('keyup', this.keyUp.bind(this), false);

        // this._map.canvas.addEventListener('keyup', this.keyUp.bind(this), false);

        document.removeEventListener('keyup', this.keyUp.bind(this), false);
        
        document.addEventListener('keyup', this.keyUp.bind(this), false);
    }

    /**
    * Handles key up event
    * @param {KeyboardEvent} event The fired event
    */
    async keyUp(event: KeyboardEvent) {

        // plot texture based of brush
        if (event.key == "Enter") {

            for (const knot of this._map.knotManager.knots) {
                knot.interact(this._map.glContext, "enter", this._map.mapGrammar);
            }

            this._map.render();

        }

        // clean abstract surfaces
        if (event.key == "r") {

            for (const knot of this._map.knotManager.knots) {
                knot.interact(this._map.glContext, "r", this._map.mapGrammar);
            }

            this._map.render();
        }

        // select a building to do the footprint plot
        if (event.key == "t") {
            for (const knot of this._map.knotManager.knots) {
                knot.interact(this._map.glContext, "t", this._map.mapGrammar, this._map.mouse.currentPoint);
            }
        }

        if (event.key == "q") {
            this._map.layerManager.filterBbox = []; // reset filter
            this._map.updateGrammarPlotsData();
            this._map.render();
        }

    }
}
