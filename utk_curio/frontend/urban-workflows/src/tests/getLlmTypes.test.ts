import { getLlmTypes } from "../NotebookConvertor";
import {Cell} from "../NotebookConvertor";

describe("getLlmTypes", ()=>{
    // beforeEach(() => {
    //     global.fetch = jest.fn();
    // });

    // afterEach(() => {
    //     jest.resetAllMocks();
    // });

    test("Empty data", async () => {
        const ambiguous: Cell[] = [];
        const result = await getLlmTypes(ambiguous, "http://127.0.0.1:5002");
        expect(result).toEqual({});
    })

    // This prob won't output anything
    test("An actual API call, because I need to know what the heck I am recieving to being with", async () => {
        const ambiguous: Cell[] = [{index: 1, code: "x = 1 "}];
        const result = await getLlmTypes(ambiguous, "http://127.0.0.1:5002");
        expect(result).toEqual({});
    })
})

// cd utk_curio/frontend/urban-workflows
// npm test -- getLlmTypes