import { GrammarMethods } from './grammar-methods';
import { Environment } from './environment';

export class InteractionChannel {

    static getGrammar: Function;
    static modifyGrammar: Function;
    static modifyGrammarVisibility: Function;

    static passedVariables: { [key: string] : any} = {};

    static setModifyGrammarVisibility(modifyGrammar: Function): void {
        InteractionChannel.modifyGrammarVisibility = modifyGrammar;
    }

    static getModifyGrammarVisibility(): Function{
        return InteractionChannel.modifyGrammarVisibility;
    }

    static addToPassedVariables(name: string, value: any){
        InteractionChannel.passedVariables[name] = value;
    }

    static getPassedVariable(name: string){
        return InteractionChannel.passedVariables[name];
    }

    static sendData(variable: {name: string, value: any}): void {

        const url = `${Environment.backend}`;

        let grammar = GrammarMethods.grammar;

        if(grammar != undefined){
            if(grammar.variables) {
                for(let varr of grammar.variables) {
                    if(varr.name == variable.name) {
                        varr.value = variable.value;
                    }
                }
            }

            GrammarMethods.applyGrammar(url, grammar, "InteractionChannel", () => {}, "");
        }
        
    }
}
