declare const global: typeof globalThis;
declare const process: { env: Record<string, string | undefined> };
declare const require: (id: string) => any;

declare module 'react-dom';
declare module 'react-dom/client';
declare module '*.css';

// autk-grammar's `./data` entry, which `moduleResolution: node` does not find
// through the package's `exports`: its own types, where the package keeps them.
declare module '@urban-toolkit/autk-grammar/data' {
    export * from '@urban-toolkit/autk-grammar/dist/data/autk-grammar-data';
}

declare module '*.module.css' {
    const classes: { [key: string]: string };
    export default classes;
}

declare module '*.png' {
    const src: string;
    export default src;
}

declare module '*.jpg' {
    const src: string;
    export default src;
}

declare module '*.jpeg' {
    const src: string;
    export default src;
}

declare module '*.gif' {
    const src: string;
    export default src;
}

declare module '*.svg' {
    const src: string;
    export default src;
}
