declare namespace MiniSimContracts {
    const PROTOCOL = "seedcore.mini-lab.worker.v2";
    const MODEL_SCHEMA = "seedcore.mini-lab.planar-model.v1";
    const ENGINE = "0.1.0-planar-arm";
    const DT: number, TOTAL_TICKS = 2880, CHUNK_TICKS = 8;
    const POOL_SIZE = 3, BUFFER_BYTES: number, MAX_INPUTS = 32;
    interface Settings {
        target: [number, number];
        strength: number;
        mass: number;
        motors: boolean;
        gravity: boolean;
    }
    interface Control {
        target: [number, number];
        strength: number;
        motors: boolean;
    }
    interface State {
        q: number[];
        velocity: number[];
        time: number;
    }
    interface Identity {
        modelDigest: string;
        recipeDigest: string;
    }
    interface Envelope extends Identity {
        protocol: typeof PROTOCOL;
        runId: number;
        revision: number;
        sequence: number;
        applicationTick: number;
    }
    type Command = Envelope & ({
        type: 'reset';
        settings: Settings;
    } | {
        type: 'start' | 'pause' | 'step' | 'checkpoint';
    } | {
        type: 'restore';
        checkpoint: RunCheckpoint;
    } | {
        type: 'set-control';
        control: Control;
    });
    interface RunCheckpoint extends Identity {
        schema: 'seedcore.mini-lab.checkpoint.v1';
        engine: string;
        buildDigest: string;
        tick: number;
        state: State;
        control: Control;
        started: boolean;
        inputs: AppliedInput[];
    }
    function validCheckpoint(value: unknown, identity: Identity, buildDigest: string): value is RunCheckpoint;
    interface Recycle {
        protocol: typeof PROTOCOL;
        type: 'recycle';
        bufferId: number;
        frameSequence: number;
        buffer: ArrayBuffer;
    }
    interface Snapshot {
        bufferId: number;
        frameSequence: number;
        sampleCount: number;
        buffer: ArrayBuffer;
    }
    interface AppliedInput {
        sequence: number;
        applicationTick: number;
        control: Control;
    }
    interface Diagnostics {
        chunks: number;
        maxChunkMs: number;
        activeWallMs: number;
        simulatedMs: number;
        realtimeRatio: number | null;
        bufferWaits: number;
        allocatedBuffers: number;
        maxInFlight: number;
    }
    interface Reply extends Identity {
        protocol: typeof PROTOCOL;
        type: 'update' | 'error' | 'queued' | 'applied' | 'checkpoint';
        runId: number;
        revision: number;
        sequence: number;
        frameSequence: number;
        applicationTick: number;
        appliedTick: number | null;
        tick: number;
        status: 'ready' | 'running' | 'paused' | 'complete' | 'error';
        state: State;
        sampleCount: number;
        buffer?: ArrayBuffer;
        bufferId?: number;
        diagnostics: Diagnostics;
        checkpoint?: RunCheckpoint;
        backend?: string;
        buildDigest?: string;
        input?: AppliedInput;
        error?: string;
    }
    function validControl(value: unknown): value is Control;
    function validSettings(value: unknown): value is Settings;
    function validEnvelope(value: unknown): value is Command;
    function validState(value: unknown, tick: number): value is State;
    function sha256Ascii(text: string): string;
    function sha256Bytes(input: Uint8Array): string;
    function compile(settings: Settings): {
        descriptor: {
            schema: string;
            engine: string;
            profile: string;
            source: {
                id: string;
                license: string;
                inertiaRecipe: string;
            };
            frame: {
                units: string;
                handedness: string;
                up: string;
                quaternionOrder: string;
                worldZUpEmbedding: string;
            };
            parameters: {
                l1: number;
                l2: number;
                m1: number;
                m2: number;
                gravity: number;
                damping: number;
            };
            nq: number;
            nv: number;
            joints: {
                id: string;
                index: number;
                parent: number;
                type: string;
                axis: number[];
            }[];
            bodies: {
                id: string;
                index: number;
                joint: number;
                center: number;
                inertia: number;
            }[];
            capabilities: string[];
        };
        parameters: {
            l1: number;
            l2: number;
            m1: number;
            m2: number;
            gravity: number;
            damping: number;
        };
        modelDigest: string;
        recipe: {
            schema: string;
            modelDigest: string;
            engine: string;
            controller: string;
            control: Control;
            dt: number;
            totalTicks: number;
            samplePeriodTicks: number;
            initial: {
                q: number[];
                velocity: number[];
            };
            rng: string;
        };
        recipeDigest: string;
    };
    function pack(buffer: ArrayBuffer, samples: State[]): void;
    function unpack(buffer: ArrayBuffer, sampleCount: number): State[];
}
declare const module: {
    exports: unknown;
} | undefined;
