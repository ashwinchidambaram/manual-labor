/* eslint-disable */
/** AUTO-GENERATED from src/api/openapi.json by scripts/gen-api.mjs - do not edit. Regenerate: npm run gen-api */

export interface paths {
    "/api/agent/accept-all-passing": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Accept All Passing */
        post: operations["accept_all_passing"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/agent/proposals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Proposals */
        get: operations["list_proposals"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/agent/proposals/{proposal_id}/accept": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Accept Proposal */
        post: operations["accept_proposal"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/agent/proposals/{proposal_id}/edit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Edit Proposal */
        post: operations["edit_proposal"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/agent/proposals/{proposal_id}/reject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reject Proposal */
        post: operations["reject_proposal"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/agent/run": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Agent Run */
        post: operations["agent_run"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/articles/{article_id}/figures": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Rail */
        get: operations["get_rail"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/calibration": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Calibration */
        get: operations["get_calibration"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/calibration/apply": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Apply Calibration */
        post: operations["apply_calibration"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/config/apply-tier": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Apply Tier */
        post: operations["apply_tier"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/config/threshold": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Put Threshold */
        put: operations["put_threshold"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/decisions/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export Decisions */
        get: operations["export_decisions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/docs/{slug}/pages/{page}.png": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Page Png */
        get: operations["get_page_png"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/docs/{slug}/pages/{page}/blocks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Page Blocks */
        get: operations["get_page_blocks"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/docs/{slug}/source": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Source */
        get: operations["get_source"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Start Export */
        post: operations["start_export"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/export/override": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Export Override */
        post: operations["export_override"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/export/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Export Status */
        get: operations["export_status"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/figures/{fid}/attach": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Attach Figure */
        post: operations["attach_figure"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/figures/{fid}/bbox": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Put Bbox */
        put: operations["put_bbox"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/figures/{fid}/detach": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Detach Figure */
        post: operations["detach_figure"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/figures/{fid}/image": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Figure Image */
        get: operations["get_figure_image"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/flags": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Flags */
        get: operations["get_flags"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/flags/{flag_id}/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resolve Flag */
        post: operations["resolve_flag"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Jobs */
        get: operations["list_jobs"];
        put?: never;
        /** Post Job */
        post: operations["post_job"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Job */
        get: operations["get_job"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Job */
        post: operations["cancel_job"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/jobs/{job_id}/log": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Job Log */
        get: operations["get_job_log"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Learning */
        get: operations["get_learning"];
        /** Put Learning */
        put: operations["put_learning"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning/activate/{snapshot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Activate Snapshot */
        post: operations["activate_snapshot"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning/items/{item_id}/disable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Disable Item */
        post: operations["disable_item"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning/publish/{snapshot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Publish Snapshot */
        post: operations["publish_snapshot"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning/reset": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reset Learning */
        post: operations["reset_learning"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning/rollback/{snapshot_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Rollback Snapshot
         * @description Rollback is activation of an earlier snapshot (design 07 section 9).
         */
        post: operations["rollback_snapshot"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/learning/snapshots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Snapshots */
        get: operations["list_snapshots"];
        put?: never;
        /** Create Snapshot */
        post: operations["create_snapshot"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/probe": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Probe */
        get: operations["get_probe"];
        put?: never;
        /** Run Probe */
        post: operations["run_probe"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/project": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Project */
        get: operations["get_project"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scope/blocks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Blocks
         * @description Per-block type/status/numeric flag so the client can compute live counts (design 08 G1).
         *     Statuses follow the current threshold; docs that are not scored yet are omitted.
         */
        get: operations["get_blocks"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scope/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Post Confirm */
        post: operations["post_confirm"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scope/groups": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Groups */
        get: operations["get_groups"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scope/models": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Models */
        get: operations["get_models"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scope/regroup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Post Regroup */
        post: operations["post_regroup"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scope/selection": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Selection */
        get: operations["get_selection"];
        /** Put Selection */
        put: operations["put_selection"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/scope/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Summary */
        get: operations["get_summary"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Sources */
        get: operations["list_sources"];
        put?: never;
        /** Upload Sources */
        post: operations["upload_sources"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Status */
        get: operations["get_status"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/verify/actions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Post Action
         * @description Approve / edit / flag / skip / back. An edit that fails the faithfulness check is a
         *     409 `edit_conflict` carrying the diff; re-send with `confirm_content_change=true` to store
         *     it as a human edit.
         */
        post: operations["post_action"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/verify/blocks/{block_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Block */
        get: operations["get_block"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/verify/cursor": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Cursor */
        get: operations["get_cursor"];
        /** Put Cursor */
        put: operations["put_cursor"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/verify/queue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Queue
         * @description `view_threshold` is a view filter for this read only; it never approves anything.
         */
        get: operations["get_queue"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AgentRunIn */
        AgentRunIn: {
            /** Docs */
            docs?: string[] | null;
            /** Request Id */
            request_id?: string;
        };
        /** ApiErrorBody */
        ApiErrorBody: {
            /** Code */
            code: string;
            /** Detail */
            detail: string;
        };
        /** ApplyTierIn */
        ApplyTierIn: {
            /**
             * Force
             * @default false
             */
            force: boolean;
            /** Request Id */
            request_id?: string;
            /**
             * Tier
             * @enum {string}
             */
            tier: "small" | "medium" | "large" | "api";
        };
        /** ApplyTierOut */
        ApplyTierOut: {
            models: components["schemas"]["TaskModels"];
            /** Stale */
            stale: components["schemas"]["NodeState"][];
        };
        /**
         * ArticleSplit
         * @enum {string}
         */
        ArticleSplit: "per_topic" | "per_document";
        /** AttachIn */
        AttachIn: {
            /** Anchor Block Id */
            anchor_block_id?: string | null;
            /** Article Id */
            article_id: string;
            /** Request Id */
            request_id?: string;
        };
        /** AttachOut */
        AttachOut: {
            job: components["schemas"]["JobInfo"];
            override: components["schemas"]["AttachOverride"];
        };
        /** AttachOverride */
        AttachOverride: {
            /** Anchor Block Id */
            anchor_block_id?: string | null;
            /** Article Id */
            article_id: string;
            /** Figure Id */
            figure_id: string;
            /**
             * Op
             * @enum {string}
             */
            op: "attach" | "detach";
            /** Seq */
            seq: number;
        };
        /**
         * AttachRule
         * @enum {string}
         */
        AttachRule: "caption_ref" | "caption_match" | "proximity" | "none" | "human";
        /** BboxIn */
        BboxIn: {
            /** Bbox */
            bbox: number[];
            /** Request Id */
            request_id?: string;
        };
        /** BboxOut */
        BboxOut: {
            job: components["schemas"]["JobInfo"];
        };
        /** Block */
        Block: {
            /** Bbox */
            bbox?: number[] | null;
            /** Clean Text */
            clean_text?: string | null;
            /** Confidence */
            confidence?: number | null;
            /** Doc Id */
            doc_id: string;
            faithfulness?: components["schemas"]["FaithfulnessResult"] | null;
            /** Figure Id */
            figure_id?: string | null;
            /**
             * Has Numeric Spec
             * @default false
             */
            has_numeric_spec: boolean;
            /** Heading Level */
            heading_level?: number | null;
            /** Id */
            id: string;
            /**
             * Numbers Verified
             * @default false
             */
            numbers_verified: boolean;
            /** Numeric Tokens */
            numeric_tokens?: string[];
            /** Ocr Words */
            ocr_words?: components["schemas"]["OcrWord"][] | null;
            /** Order By Parser */
            order_by_parser?: {
                [key: string]: number;
            };
            /** Page */
            page: number;
            /** Raw Source */
            raw_source: string;
            /** Raw Text */
            raw_text: string;
            /** Raw Text By Parser */
            raw_text_by_parser?: {
                [key: string]: string;
            };
            /** Reading Order */
            reading_order: number;
            /** Section Number */
            section_number?: string | null;
            /** Signals */
            signals?: components["schemas"]["Signal"][];
            /** @default queued */
            status: components["schemas"]["BlockStatus"];
            table?: components["schemas"]["TableData"] | null;
            type: components["schemas"]["BlockType"];
        };
        /** BlockDetail */
        BlockDetail: {
            /** Article Ids */
            article_ids?: string[];
            block: components["schemas"]["Block"];
            /** Figures */
            figures?: components["schemas"]["FigureRailItem"][];
            /** Flags */
            flags?: components["schemas"]["Flag"][];
            /** History */
            history?: components["schemas"]["DecisionRecord"][];
            learning?: components["schemas"]["LearningUse"];
            page: components["schemas"]["PageRef"];
            /** Parser Texts */
            parser_texts?: {
                [key: string]: string;
            };
            /** Why */
            why?: components["schemas"]["WhyItem"][];
        };
        /**
         * BlockStatus
         * @enum {string}
         */
        BlockStatus: "auto_approved" | "queued" | "approved" | "edited" | "flagged" | "rejected";
        /**
         * BlockType
         * @enum {string}
         */
        BlockType: "heading" | "paragraph" | "list" | "table" | "figure" | "caption" | "header" | "footer" | "other";
        /** Body_upload_sources */
        Body_upload_sources: {
            /** Files */
            files: string[];
        };
        /** CalibrationAB */
        CalibrationAB: {
            /** Baseline Edit Rate */
            baseline_edit_rate?: number | null;
            /** Baseline N */
            baseline_n: number;
            /** Learned Edit Rate */
            learned_edit_rate?: number | null;
            /** Learned N */
            learned_n: number;
            /**
             * Verdict
             * @enum {string}
             */
            verdict: "learned_better" | "learned_worse" | "insufficient";
        };
        /** CalibrationApplyIn */
        CalibrationApplyIn: {
            /** Request Id */
            request_id?: string;
            /** Threshold */
            threshold: number;
        };
        /** CalibrationApplyOut */
        CalibrationApplyOut: {
            /** Threshold */
            threshold: number;
        };
        /** CalibrationBucket */
        CalibrationBucket: {
            /** Edit Rate */
            edit_rate?: number | null;
            /** Edited */
            edited: number;
            /** Hi */
            hi: number;
            /** Lo */
            lo: number;
            /** N */
            n: number;
        };
        /** CalibrationReport */
        CalibrationReport: {
            ab?: components["schemas"]["CalibrationAB"] | null;
            /** Buckets */
            buckets?: components["schemas"]["CalibrationBucket"][];
            /** Suggested Threshold */
            suggested_threshold?: number | null;
            /** Target Edit Rate */
            target_edit_rate: number;
        };
        /**
         * CleanupConfig
         * @description Cleanup stage settings (module 5): when the LLM pass runs, and figure descriptions.
         */
        CleanupConfig: {
            /**
             * Describe
             * @default true
             */
            describe: boolean;
            /**
             * Llm
             * @default residual
             * @enum {string}
             */
            llm: "off" | "residual" | "always";
        };
        /** ConfirmIn */
        ConfirmIn: {
            /** Request Id */
            request_id?: string;
        };
        /** CoverageReport */
        CoverageReport: {
            /** Doc Id */
            doc_id: string;
            /** Selectable */
            selectable: number;
            /** Selected */
            selected: number;
            /** Structure */
            structure: components["schemas"]["GroupCoverage"][];
            /** Topics */
            topics: components["schemas"]["GroupCoverage"][];
        };
        /** CpuInfo */
        CpuInfo: {
            /** Cores Logical */
            cores_logical: number | null;
            /** Cores Physical */
            cores_physical: number | null;
            /** Model */
            model: string;
        };
        /** Cursor */
        Cursor: {
            /** Current Block Id */
            current_block_id?: string | null;
            /** Doc Filter */
            doc_filter?: string | null;
            /** @default worst_first */
            sort: components["schemas"]["QueueSort"];
            /** Trail */
            trail?: string[];
            /** View Threshold */
            view_threshold?: number | null;
        };
        /** CursorIn */
        CursorIn: {
            /** Current Block Id */
            current_block_id?: string | null;
            /** Doc Filter */
            doc_filter?: string | null;
            /** Request Id */
            request_id?: string;
            /** @default worst_first */
            sort: components["schemas"]["QueueSort"];
            /** View Threshold */
            view_threshold?: number | null;
        };
        /** Decision */
        Decision: {
            action: components["schemas"]["DecisionAction"];
            /** Block Id */
            block_id: string;
            /** Edited Text */
            edited_text?: string | null;
            /** Flag Id */
            flag_id?: string | null;
            /** Score */
            score: number | null;
            /** Seq */
            seq: number;
            /** Signals */
            signals: components["schemas"]["Signal"][];
            /** Threshold */
            threshold: number;
            /**
             * Timestamp
             * Format: date-time
             */
            timestamp: string;
        };
        /**
         * DecisionAction
         * @enum {string}
         */
        DecisionAction: "approve" | "edit" | "flag" | "skip";
        /** DecisionRecord */
        DecisionRecord: {
            /** Action Id */
            action_id: number;
            decision: components["schemas"]["Decision"];
            /** Doc Id */
            doc_id: string;
            /** Faith Passed */
            faith_passed?: boolean | null;
            /** Human Edit Diff */
            human_edit_diff?: components["schemas"]["DiffOp"][] | null;
            /**
             * Learning Provenance
             * @default baseline
             */
            learning_provenance: string;
            /**
             * Numbers Verified
             * @default false
             */
            numbers_verified: boolean;
            /** Raw Sha256 */
            raw_sha256: string;
            /** Shown Text Sha256 */
            shown_text_sha256: string;
            /**
             * Source
             * @default human
             * @enum {string}
             */
            source: "human" | "agent";
        };
        /** DiffOp */
        DiffOp: {
            /** Allowed */
            allowed: boolean;
            /** Clean */
            clean: string;
            /** Clean End */
            clean_end: number;
            /** Clean Start */
            clean_start: number;
            op: components["schemas"]["DiffOpKind"];
            /** Raw */
            raw: string;
            /** Raw End */
            raw_end: number;
            /** Raw Start */
            raw_start: number;
        };
        /**
         * DiffOpKind
         * @enum {string}
         */
        DiffOpKind: "equal" | "insert" | "delete" | "replace" | "reorder";
        /** DocGroups */
        DocGroups: {
            coverage: components["schemas"]["CoverageReport"];
            /** Doc Id */
            doc_id: string;
            groups: components["schemas"]["GroupsFile"];
        };
        /**
         * DocKind
         * @enum {string}
         */
        DocKind: "born_digital_pdf" | "scanned_pdf" | "docx";
        /** DocLearning */
        DocLearning: {
            /**
             * Clean
             * @default baseline
             */
            clean: string;
            /**
             * Group
             * @default baseline
             */
            group: string;
        };
        /** DocReadiness */
        DocReadiness: {
            /** Doc Id */
            doc_id: string;
            /**
             * Stale
             * @default false
             */
            stale: boolean;
            /**
             * State
             * @enum {string}
             */
            state: "ready" | "pending";
            /** Waiting For */
            waiting_for?: string | null;
        };
        /** DocStatus */
        DocStatus: {
            /** Doc Id */
            doc_id: string;
            kind: components["schemas"]["DocKind"];
            learning?: components["schemas"]["DocLearning"];
            /** Nodes */
            nodes: components["schemas"]["NodeState"][];
            /**
             * Orphaned Decisions
             * @default 0
             */
            orphaned_decisions: number;
            /** Pages */
            pages: number;
        };
        /** EditConflict */
        EditConflict: {
            /** Diff */
            diff: components["schemas"]["DiffOp"][];
            /** Numeric Changes */
            numeric_changes: string[];
            /** Violations */
            violations: components["schemas"]["FaithfulnessViolation"][];
        };
        /** EditConflictBody */
        EditConflictBody: {
            /** Code */
            code: string;
            conflict: components["schemas"]["EditConflict"];
            /** Detail */
            detail: string;
        };
        /** ExportStatus */
        ExportStatus: {
            /** Open Flags */
            open_flags: number;
            /** Overrides */
            overrides?: components["schemas"]["Override"][];
            /** Unlocked */
            unlocked: boolean;
        };
        /**
         * Extraction
         * @enum {string}
         */
        Extraction: "native" | "vector" | "crop";
        /**
         * FaithViolationKind
         * @enum {string}
         */
        FaithViolationKind: "insertion" | "deletion" | "numeric_mismatch" | "reorder";
        /** FaithfulnessResult */
        FaithfulnessResult: {
            /** Alignment Ratio */
            alignment_ratio: number;
            /** Diff */
            diff: components["schemas"]["DiffOp"][];
            /** Numeric Variants */
            numeric_variants?: components["schemas"]["NumericVariant"][];
            /** Passed */
            passed: boolean;
            /** Violations */
            violations: components["schemas"]["FaithfulnessViolation"][];
        };
        /** FaithfulnessViolation */
        FaithfulnessViolation: {
            /** Clean */
            clean: string;
            /** Clean End */
            clean_end: number | null;
            /** Clean Start */
            clean_start: number | null;
            kind: components["schemas"]["FaithViolationKind"];
            /** Raw */
            raw: string;
            /** Raw End */
            raw_end: number | null;
            /** Raw Start */
            raw_start: number | null;
        };
        /** FigureAttachment */
        FigureAttachment: {
            /** Anchor Block Id */
            anchor_block_id?: string | null;
            /** Article Id */
            article_id: string;
            /** Confidence */
            confidence?: number | null;
            /** Rule */
            rule: string;
        };
        /** FigureRailItem */
        FigureRailItem: {
            attachment?: components["schemas"]["FigureAttachment"] | null;
            /** Block Id */
            block_id: string;
            /** Figure Id */
            figure_id: string;
            /** Image Url */
            image_url: string;
            record: components["schemas"]["FigureRecord"];
            status: components["schemas"]["BlockStatus"];
        };
        /** FigureRecord */
        FigureRecord: {
            /** Articles */
            articles: string[];
            attach_rule: components["schemas"]["AttachRule"];
            /** Bbox */
            bbox: number[] | null;
            /** Caption Original */
            caption_original: string | null;
            /** Confidence */
            confidence: number;
            /** Description Generated */
            description_generated: string | null;
            extraction: components["schemas"]["Extraction"];
            /** File */
            file: string;
            /** Height */
            height: number;
            /** Id */
            id: string;
            /** Page */
            page: number;
            /** Phash */
            phash: string;
            /** Product Model */
            product_model: string | null;
            review: components["schemas"]["BlockStatus"];
            /** Source Doc */
            source_doc: string;
            /** Svg */
            svg: string | null;
            /** Tags */
            tags: string[];
            /** Width */
            width: number;
        };
        /** Flag */
        Flag: {
            category: components["schemas"]["FlagCategory"];
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: string;
            /** Note */
            note?: string | null;
            /** Resolution */
            resolution?: string | null;
            /** Resolved At */
            resolved_at?: string | null;
            /** @default open */
            status: components["schemas"]["FlagStatus"];
            /** Target Id */
            target_id: string;
        };
        /**
         * FlagCategory
         * @enum {string}
         */
        FlagCategory: "wrong_text" | "missing_figure" | "wrong_grouping" | "bad_crop" | "table_structure";
        /** FlagIn */
        FlagIn: {
            category: components["schemas"]["FlagCategory"];
            /** Note */
            note?: string | null;
            /** Target Id */
            target_id?: string | null;
        };
        /**
         * FlagStatus
         * @enum {string}
         */
        FlagStatus: "open" | "resolved";
        /** GpuInfo */
        GpuInfo: {
            /** Name */
            name: string;
            /** Unified */
            unified: boolean;
            /**
             * Vendor
             * @enum {string}
             */
            vendor: "nvidia" | "amd" | "apple" | "none";
            /** Vram Gb */
            vram_gb: number | null;
        };
        /** Group */
        Group: {
            /** Block Count */
            block_count: number;
            /** Block Ids */
            block_ids: string[];
            /** Cohesion */
            cohesion?: number | null;
            /** Doc Id */
            doc_id: string;
            /** Figure Count */
            figure_count: number;
            /** Id */
            id: string;
            /**
             * Is Unassigned
             * @default false
             */
            is_unassigned: boolean;
            /**
             * Level
             * @default 0
             */
            level: number;
            /** Page Ranges */
            page_ranges: components["schemas"]["PageRange"][];
            /** Parent Id */
            parent_id?: string | null;
            /** Section Ids */
            section_ids?: string[];
            /** Section Number */
            section_number?: string | null;
            /** Slug */
            slug: string;
            /** Title */
            title: string;
            view: components["schemas"]["GroupView"];
        };
        /** GroupCoverage */
        GroupCoverage: {
            /** Fraction */
            fraction: number | null;
            /** Group Id */
            group_id: string;
            /** Selected */
            selected: number;
            /** Subtree Fraction */
            subtree_fraction: number | null;
            /** Subtree Selected */
            subtree_selected: number | null;
            /** Subtree Total */
            subtree_total: number | null;
            /** Total */
            total: number;
            view: components["schemas"]["GroupView"];
        };
        /** GroupOverlap */
        GroupOverlap: {
            /** Blocks */
            blocks: number;
            /** Section Id */
            section_id: string;
            /** Topic Id */
            topic_id: string;
        };
        /**
         * GroupOverride
         * @description A human regrouping decision, appended to docs/<slug>/group_overrides.json.
         */
        GroupOverride: {
            /** Block Id */
            block_id?: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "move" | "rename";
            /** Seq */
            seq: number;
            /** Title */
            title?: string | null;
            /** To Topic Slug */
            to_topic_slug?: string | null;
            /** Topic Slug */
            topic_slug?: string | null;
        };
        /**
         * GroupView
         * @enum {string}
         */
        GroupView: "structure" | "topic";
        /**
         * GroupingParams
         * @description Every grouping constant, frozen into groups.json so a result can be explained.
         */
        GroupingParams: {
            /** D Cut */
            d_cut: number;
            /** Embed Batch */
            embed_batch: number;
            /** Embed Prefix */
            embed_prefix: string;
            /** K Max Divisor */
            k_max_divisor: number;
            /** Llm Stragglers */
            llm_stragglers: boolean;
            /** Low Cohesion */
            low_cohesion: number;
            /** Max Topic Blocks */
            max_topic_blocks: number;
            /** Min Topic Blocks */
            min_topic_blocks: number;
            /** N Candidates */
            n_candidates: number;
            /** Name Sample */
            name_sample: number;
            /** Name Tokens */
            name_tokens: number;
            /** Page Window */
            page_window: number;
            /** Small Doc */
            small_doc: number;
            /** Straggler Batch */
            straggler_batch: number;
            /** Summary Tokens */
            summary_tokens: number;
            /** T Assign */
            t_assign: number;
            /** T Candidate */
            t_candidate: number;
            /** Title Max */
            title_max: number;
            /** Topic Slug Max */
            topic_slug_max: number;
        };
        /**
         * GroupsFile
         * @description docs/<slug>/groups.json: both views of one document, the accounting of blocks that sit in
         *     no group, and the provenance needed to explain or reproduce the result.
         */
        GroupsFile: {
            /** Algo Version */
            algo_version: string;
            /** Doc Id */
            doc_id: string;
            /** Embedding Dim */
            embedding_dim: number;
            /** Embedding Model */
            embedding_model: string;
            /** Fingerprint */
            fingerprint: string;
            /** Grouping Model */
            grouping_model: string;
            /** Learning Snapshot */
            learning_snapshot: string;
            /** Overlap */
            overlap: components["schemas"]["GroupOverlap"][];
            /** Overrides Applied */
            overrides_applied: number;
            /** Overrides Stale */
            overrides_stale: number[];
            params: components["schemas"]["GroupingParams"];
            /** Stragglers */
            stragglers: components["schemas"]["StragglerRecord"][];
            /** Structure */
            structure: components["schemas"]["Group"][];
            /** Title Sources */
            title_sources: {
                [key: string]: components["schemas"]["TitleSource"];
            };
            /** Topic Error */
            topic_error?: string | null;
            /**
             * Topic Status
             * @enum {string}
             */
            topic_status: "ok" | "failed";
            /** Topics */
            topics: components["schemas"]["Group"][];
            /** Unassigned */
            unassigned: components["schemas"]["UnassignedEntry"][];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** JobInfo */
        JobInfo: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Doc */
            doc?: string | null;
            /** Error */
            error?: string | null;
            /** Finished At */
            finished_at?: string | null;
            /** Id */
            id: string;
            /** Kind */
            kind: string;
            /** Message */
            message?: string | null;
            /** Node */
            node?: string | null;
            /** Pid */
            pid?: number | null;
            /** Plan */
            plan?: {
                [key: string]: unknown;
            };
            /**
             * Progress
             * @default 0
             */
            progress: number;
            /** Resumed From */
            resumed_from?: string | null;
            /** Started At */
            started_at?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "queued" | "running" | "done" | "failed" | "cancelled" | "interrupted";
            /**
             * Units Done
             * @default 0
             */
            units_done: number;
            /**
             * Units Total
             * @default 0
             */
            units_total: number;
        };
        /**
         * LearningConfig
         * @description Self-improvement settings (module 7). `enabled` off means baseline behaviour exactly,
         *     even when learned state exists on disk. `use_global` / `contribute_global` opt in to the
         *     cross-project store ($MANUALLABOR_HOME/learning).
         */
        LearningConfig: {
            /**
             * Contribute Global
             * @default false
             */
            contribute_global: boolean;
            /**
             * Enabled
             * @default false
             */
            enabled: boolean;
            /**
             * Use Global
             * @default false
             */
            use_global: boolean;
        };
        /** LearningFlagsIn */
        LearningFlagsIn: {
            /** Contribute Global */
            contribute_global?: boolean | null;
            /** Enabled */
            enabled?: boolean | null;
            /** Request Id */
            request_id?: string;
            /** Use Global */
            use_global?: boolean | null;
        };
        /** LearningState */
        LearningState: {
            /** Active */
            active?: string | null;
            /**
             * Contribute Global
             * @default false
             */
            contribute_global: boolean;
            /**
             * Enabled
             * @default false
             */
            enabled: boolean;
            /**
             * Provenance
             * @default baseline
             */
            provenance: string;
            /** Snapshots */
            snapshots?: components["schemas"]["SnapshotInfo"][];
            /**
             * Use Global
             * @default false
             */
            use_global: boolean;
        };
        /** LearningUse */
        LearningUse: {
            /** Few Shot */
            few_shot?: string[];
            /** Learned Rules */
            learned_rules?: string[];
            /**
             * Provenance
             * @default baseline
             */
            provenance: string;
        };
        /** ModelRef */
        ModelRef: {
            /** Api Base */
            api_base?: string | null;
            /** Api Key Env */
            api_key_env?: string | null;
            /** Model */
            model: string;
            /** Provider */
            provider: string;
        };
        /** NodeState */
        NodeState: {
            /** Node */
            node: string;
            /** Reason */
            reason?: string | null;
            /**
             * State
             * @enum {string}
             */
            state: "fresh" | "stale" | "missing" | "failed";
        };
        /** NumericVariant */
        NumericVariant: {
            /** Chosen */
            chosen: string;
            /** Raw */
            raw: string;
            /** Reason */
            reason: string;
            /**
             * Source
             * @enum {string}
             */
            source: "textlayer" | "ocr";
        };
        /**
         * OcrEngine
         * @enum {string}
         */
        OcrEngine: "auto" | "rapidocr" | "tesseract";
        /** OcrWord */
        OcrWord: {
            /** Bbox */
            bbox?: number[] | null;
            /** Confidence */
            confidence: number;
            /** Text */
            text: string;
        };
        /** OllamaModel */
        OllamaModel: {
            /** Digest */
            digest: string;
            /** Name */
            name: string;
            /** Size Gb */
            size_gb: number | null;
        };
        /** OllamaStatus */
        OllamaStatus: {
            /** Host */
            host: string;
            /** Installed */
            installed: boolean;
            /** Models */
            models: components["schemas"]["OllamaModel"][];
            /** Reachable */
            reachable: boolean;
            /** Version */
            version: string | null;
        };
        /** Override */
        Override: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            /** Flag Id */
            flag_id?: string | null;
            /** Reason */
            reason: string;
            /** Target Id */
            target_id?: string | null;
        };
        /** OverrideIn */
        OverrideIn: {
            /** Flag Id */
            flag_id?: string | null;
            /** Reason */
            reason: string;
            /** Request Id */
            request_id?: string;
            /** Target Id */
            target_id?: string | null;
        };
        /** PageBlock */
        PageBlock: {
            /** Bbox */
            bbox: number[];
            /** Block Id */
            block_id: string;
            status: components["schemas"]["BlockStatus"];
            type: components["schemas"]["BlockType"];
        };
        /** PageRange */
        PageRange: {
            /** End */
            end: number;
            /** Start */
            start: number;
        };
        /** PageRef */
        PageRef: {
            /** Doc Id */
            doc_id: string;
            /** Height */
            height: number;
            /** Page */
            page: number;
            /** Render Url */
            render_url?: string | null;
            /** Source Url */
            source_url: string;
            /** Width */
            width: number;
        };
        /** PlatformInfo */
        PlatformInfo: {
            /** Machine */
            machine: string;
            /** System */
            system: string;
        };
        /** PriorAttempt */
        PriorAttempt: {
            /**
             * Decided At
             * Format: date-time
             */
            decided_at: string;
            /** Proposal Id */
            proposal_id: string;
            /** Proposal Text */
            proposal_text: string;
            /** Rationale */
            rationale: string;
            status: components["schemas"]["ProposalStatus"];
        };
        /** ProbeOut */
        ProbeOut: {
            probe: components["schemas"]["ProbeResult"];
            suggestions: components["schemas"]["SuggestionTable"];
        };
        /** ProbeResult */
        ProbeResult: {
            cpu: components["schemas"]["CpuInfo"];
            /** Disk Free Gb */
            disk_free_gb: number;
            /** Disk Path */
            disk_path: string;
            /** Effective Model Memory Gb */
            effective_model_memory_gb: number;
            gpu: components["schemas"]["GpuInfo"] | null;
            /** Litellm Version */
            litellm_version: string | null;
            /** Notes */
            notes: string[];
            ollama: components["schemas"]["OllamaStatus"];
            platform: components["schemas"]["PlatformInfo"];
            /**
             * Probed At
             * Format: date-time
             */
            probed_at: string;
            /** Ram Gb */
            ram_gb: number;
            /**
             * Schema Version
             * @default 1.0
             * @constant
             */
            schema_version: "1.0";
        };
        /** ProjectConfig */
        ProjectConfig: {
            /** @default per_topic */
            article_split: components["schemas"]["ArticleSplit"];
            /**
             * Background Ocr Born Digital
             * @default true
             */
            background_ocr_born_digital: boolean;
            cleanup?: components["schemas"]["CleanupConfig"];
            learning?: components["schemas"]["LearningConfig"];
            models?: components["schemas"]["TaskModels"];
            /** Name */
            name: string;
            /**
             * Ocr Dpi
             * @default 300
             */
            ocr_dpi: number;
            /** @default auto */
            ocr_engine: components["schemas"]["OcrEngine"];
            /** Parsers */
            parsers?: string[];
            /**
             * Schema Version
             * @default 1.0
             * @constant
             */
            schema_version: "1.0";
            /**
             * Target Edit Rate
             * @default 0.02
             */
            target_edit_rate: number;
            /**
             * Threshold
             * @default 0.85
             */
            threshold: number;
        };
        /** ProjectInfo */
        ProjectInfo: {
            config: components["schemas"]["ProjectConfig"];
            learning: components["schemas"]["LearningState"];
            /** Mock */
            mock: boolean;
            /** Name */
            name: string;
            /** Root */
            root: string;
            /** Tool Version */
            tool_version: string;
        };
        /** ProjectStatus */
        ProjectStatus: {
            /** Docs */
            docs: components["schemas"]["DocStatus"][];
            /** Jobs Running */
            jobs_running?: components["schemas"]["JobInfo"][];
            /** Project */
            project: string;
            /** Unregistered Sources */
            unregistered_sources?: string[];
        };
        /** Proposal */
        Proposal: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Evidence */
            evidence: string[];
            /** Final Text */
            final_text?: string | null;
            /** Flag Id */
            flag_id: string;
            /** History */
            history?: components["schemas"]["PriorAttempt"][];
            /** Id */
            id: string;
            /** Input Hash */
            input_hash: string;
            /** Model */
            model: string;
            /** Proposal Text */
            proposal_text?: string | null;
            /** Proposed Bbox */
            proposed_bbox?: number[] | null;
            /** Rationale */
            rationale: string;
            /** Rechecks */
            rechecks?: components["schemas"]["RecheckResult"][];
            /**
             * Round
             * @default 1
             */
            round: number;
            /** @default pending */
            status: components["schemas"]["ProposalStatus"];
            /** Target Id */
            target_id: string;
        };
        /** ProposalEditIn */
        ProposalEditIn: {
            /** Request Id */
            request_id?: string;
            /** Text */
            text: string;
        };
        /**
         * ProposalStatus
         * @enum {string}
         */
        ProposalStatus: "pending" | "accepted" | "edited" | "rejected";
        /** QueueItem */
        QueueItem: {
            /** Block Id */
            block_id: string;
            /** Confidence */
            confidence?: number | null;
            /** Doc Id */
            doc_id: string;
            /**
             * Has Numeric Spec
             * @default false
             */
            has_numeric_spec: boolean;
            /** Page */
            page: number;
            /** Reasons */
            reasons?: string[];
            /**
             * Stale Doc
             * @default false
             */
            stale_doc: boolean;
            status: components["schemas"]["BlockStatus"];
            type: components["schemas"]["BlockType"];
        };
        /** QueuePage */
        QueuePage: {
            counts: components["schemas"]["ReviewCounts"];
            cursor: components["schemas"]["Cursor"];
            /** Docs */
            docs: components["schemas"]["DocReadiness"][];
            /** Items */
            items: components["schemas"]["QueueItem"][];
            /** Total */
            total: number;
        };
        /**
         * QueueSort
         * @enum {string}
         */
        QueueSort: "worst_first" | "by_page" | "figures_only";
        /** RecheckResult */
        RecheckResult: {
            /** Check */
            check: string;
            /** Detail */
            detail?: string | null;
            /** Passed */
            passed: boolean;
        };
        /** RegroupIn */
        RegroupIn: {
            /** Block Id */
            block_id?: string | null;
            /** Doc Id */
            doc_id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "move" | "rename";
            /** Request Id */
            request_id: string;
            /** Title */
            title?: string | null;
            /** To Topic Slug */
            to_topic_slug?: string | null;
            /** Topic Slug */
            topic_slug?: string | null;
        };
        /** RegroupOut */
        RegroupOut: {
            job: components["schemas"]["JobInfo"];
            override: components["schemas"]["GroupOverride"];
        };
        /**
         * RequestIn
         * @description Body of mutations that carry nothing but an idempotency key.
         */
        RequestIn: {
            /** Request Id */
            request_id?: string;
        };
        /** ResolveFlagIn */
        ResolveFlagIn: {
            /** Request Id */
            request_id?: string;
            /** Resolution */
            resolution: string;
        };
        /** ReviewActionIn */
        ReviewActionIn: {
            /** Block Id */
            block_id?: string | null;
            /**
             * Confirm Content Change
             * @default false
             */
            confirm_content_change: boolean;
            flag?: components["schemas"]["FlagIn"] | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "approve" | "edit" | "flag" | "skip" | "back";
            /** Request Id */
            request_id: string;
            /** Text */
            text?: string | null;
        };
        /** ReviewActionOut */
        ReviewActionOut: {
            /** Action Id */
            action_id: number;
            block_status?: components["schemas"]["BlockStatus"] | null;
            counts: components["schemas"]["ReviewCounts"];
            cursor: components["schemas"]["Cursor"];
            decision?: components["schemas"]["DecisionRecord"] | null;
            flag?: components["schemas"]["Flag"] | null;
            next?: components["schemas"]["QueueItem"] | null;
        };
        /** ReviewCounts */
        ReviewCounts: {
            /**
             * Approved
             * @default 0
             */
            approved: number;
            /**
             * Auto Approved
             * @default 0
             */
            auto_approved: number;
            /**
             * Edited
             * @default 0
             */
            edited: number;
            /**
             * Flagged Open
             * @default 0
             */
            flagged_open: number;
            /**
             * In Scope
             * @default 0
             */
            in_scope: number;
            /**
             * Pending
             * @default 0
             */
            pending: number;
            /**
             * Skipped
             * @default 0
             */
            skipped: number;
        };
        /** ReviewLoad */
        ReviewLoad: {
            /** Numeric Queued */
            numeric_queued: number;
            /** Queued */
            queued: number;
            /** Threshold */
            threshold: number;
        };
        /** RunPlanIn */
        RunPlanIn: {
            /**
             * Allow Reparse
             * @default false
             */
            allow_reparse: boolean;
            /** Docs */
            docs?: string[] | null;
            /** Force */
            force?: string[];
            /**
             * To
             * @default score2
             */
            to: string;
        };
        /** ScopeBlockRow */
        ScopeBlockRow: {
            /** Id */
            id: string;
            /** Numeric */
            numeric: boolean;
            status: components["schemas"]["BlockStatus"];
            type: components["schemas"]["BlockType"];
        };
        /** ScopeBlocks */
        ScopeBlocks: {
            /** Blocks */
            blocks: components["schemas"]["ScopeBlockRow"][];
            /** Doc Id */
            doc_id: string;
        };
        /** ScopeModels */
        ScopeModels: {
            models: components["schemas"]["TaskModels"];
            probe?: components["schemas"]["ProbeResult"] | null;
            suggestions?: components["schemas"]["SuggestionTable"] | null;
        };
        /** ScopeSummary */
        ScopeSummary: {
            /** Articles */
            articles: number;
            /** Articles Per Document */
            articles_per_document: number;
            /** Articles Per Topic */
            articles_per_topic: number;
            /** Blocks */
            blocks: number;
            /** Docs */
            docs: number;
            /** Figures */
            figures: number;
            /** Pages */
            pages: number;
            review_load: components["schemas"]["ReviewLoad"];
        };
        /** Selection */
        Selection: {
            /** @default topic */
            active_view: components["schemas"]["GroupView"];
            /** @default per_topic */
            article_split: components["schemas"]["ArticleSplit"];
            /** Block Ids */
            block_ids: string[];
        };
        /** SelectionOp */
        SelectionOp: {
            /** Block Ids */
            block_ids?: string[];
            /** Doc Id */
            doc_id?: string | null;
            /** Group Id */
            group_id?: string | null;
            /**
             * Op
             * @enum {string}
             */
            op: "select" | "deselect" | "select_group" | "deselect_group" | "set_view" | "set_split";
            /** Request Id */
            request_id: string;
            /** Split */
            split?: ("per_topic" | "per_document") | null;
            /**
             * Subtree
             * @default false
             */
            subtree: boolean;
            /** View */
            view?: ("structure" | "topic") | null;
        };
        /** SelectionOut */
        SelectionOut: {
            /** Coverage */
            coverage?: components["schemas"]["CoverageReport"][];
            /** Dropped */
            dropped?: string[];
            selection: components["schemas"]["Selection"];
            summary: components["schemas"]["ScopeSummary"];
        };
        /** Signal */
        Signal: {
            /** Critical */
            critical: boolean;
            /** Detail */
            detail?: string | null;
            name: components["schemas"]["SignalName"];
            /** Value */
            value: number;
        };
        /**
         * SignalName
         * @enum {string}
         */
        SignalName: "ocr_mean" | "ocr_min" | "textlayer_vs_ocr" | "parser_agreement" | "reading_order_risk" | "table_consistency" | "garbage_ratio" | "faithfulness" | "figure_method" | "figure_resolution" | "figure_attach_rule" | "has_numeric_spec" | "llm_verifier";
        /** SnapshotInfo */
        SnapshotInfo: {
            /**
             * Active
             * @default false
             */
            active: boolean;
            /** Counts */
            counts?: {
                [key: string]: number;
            };
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: string;
            /**
             * Origin
             * @default project
             */
            origin: string;
            /** Parent */
            parent?: string | null;
            /** Source First Action */
            source_first_action?: number | null;
            /** Source Last Action */
            source_last_action?: number | null;
        };
        /** SourceInfo */
        SourceInfo: {
            /** Filename */
            filename: string;
            kind: components["schemas"]["DocKind"];
            /** Nodes */
            nodes: components["schemas"]["NodeState"][];
            /** Ocr Warning */
            ocr_warning?: string | null;
            /** Pages */
            pages: number;
            /** Slug */
            slug: string;
        };
        /** StragglerRecord */
        StragglerRecord: {
            /** Block Id */
            block_id: string;
            /**
             * By
             * @enum {string}
             */
            by: "centroid" | "llm";
            /** Similarity */
            similarity: number;
            /** Topic Id */
            topic_id: string | null;
        };
        /** SuggestionTable */
        SuggestionTable: {
            /** Default Reason */
            default_reason?: string | null;
            /**
             * Default Tier
             * @enum {string}
             */
            default_tier: "small" | "medium" | "large" | "api";
            /** Pull Commands */
            pull_commands?: {
                [key: string]: string[];
            };
            /** Rows */
            rows: components["schemas"]["TaskSuggestion"][];
        };
        /** TableCell */
        TableCell: {
            /** Col */
            col: number;
            /**
             * Col Span
             * @default 1
             */
            col_span: number;
            /**
             * Is Header
             * @default false
             */
            is_header: boolean;
            /** Row */
            row: number;
            /**
             * Row Span
             * @default 1
             */
            row_span: number;
            /** Text */
            text: string;
        };
        /** TableData */
        TableData: {
            /** Cells */
            cells: components["schemas"]["TableCell"][];
            /** Markdown */
            markdown: string;
            /** N Cols */
            n_cols: number;
            /** N Rows */
            n_rows: number;
            /** Shape By Parser */
            shape_by_parser?: {
                [key: string]: components["schemas"]["TableShape"];
            };
        };
        /** TableShape */
        TableShape: {
            /** Cols */
            cols: number;
            /** Rows */
            rows: number;
        };
        /** TaskModels */
        TaskModels: {
            agent?: components["schemas"]["ModelRef"] | null;
            cleanup?: components["schemas"]["ModelRef"];
            embeddings?: components["schemas"]["ModelRef"];
            grouping?: components["schemas"]["ModelRef"];
            metadata?: components["schemas"]["ModelRef"] | null;
            verifier?: components["schemas"]["ModelRef"] | null;
            vision?: components["schemas"]["ModelRef"];
        };
        /** TaskSuggestion */
        TaskSuggestion: {
            api: components["schemas"]["TierOption"];
            large: components["schemas"]["TierOption"];
            medium: components["schemas"]["TierOption"];
            small: components["schemas"]["TierOption"];
            /**
             * Task
             * @enum {string}
             */
            task: "cleanup" | "grouping" | "vision" | "verifier" | "embeddings";
        };
        /** ThresholdIn */
        ThresholdIn: {
            /**
             * Reason
             * @default calibration
             * @enum {string}
             */
            reason: "slider" | "calibration" | "cli";
            /** Request Id */
            request_id?: string;
            /** Value */
            value: number;
        };
        /** ThresholdOut */
        ThresholdOut: {
            job: components["schemas"]["JobInfo"];
            /** Threshold */
            threshold: number;
        };
        /** TierOption */
        TierOption: {
            /** Approx Gb */
            approx_gb: number;
            /** Est Tokens Per S */
            est_tokens_per_s: number | null;
            /** Fits */
            fits: boolean;
            /** Model */
            model: string;
            /** Note */
            note?: string | null;
            /** Present */
            present: boolean;
            /** Provider */
            provider: string;
            /** Pull Command */
            pull_command: string | null;
            /**
             * Speed Class
             * @enum {string}
             */
            speed_class: "fast" | "ok" | "slow" | "n/a";
        };
        /**
         * TitleSource
         * @enum {string}
         */
        TitleSource: "heading" | "llm" | "fallback" | "human";
        /** UnassignedEntry */
        UnassignedEntry: {
            /** Block Id */
            block_id: string;
            reason: components["schemas"]["UnassignedReason"];
            view: components["schemas"]["GroupView"];
        };
        /**
         * UnassignedReason
         * @enum {string}
         */
        UnassignedReason: "header_footer" | "low_similarity" | "no_text" | "topic_failed" | "do_not_merge";
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /** WhyItem */
        WhyItem: {
            /**
             * Critical
             * @default false
             */
            critical: boolean;
            /** Detail */
            detail?: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "signal" | "rule" | "stale" | "learning";
            /** Name */
            name: string;
            /** Value */
            value?: number | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    accept_all_passing: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RequestIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Proposal"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Not Implemented */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    list_proposals: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Proposal"][];
                };
            };
            /** @description Not Implemented */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    accept_proposal: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RequestIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Proposal"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Not Implemented */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    edit_proposal: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProposalEditIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Proposal"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Not Implemented */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    reject_proposal: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                proposal_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RequestIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Proposal"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Not Implemented */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    agent_run: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["AgentRunIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Not Implemented */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    get_rail: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                article_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FigureRailItem"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_calibration: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CalibrationReport"];
                };
            };
            /** @description Not Implemented */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    apply_calibration: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CalibrationApplyIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CalibrationApplyOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Not Implemented */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    apply_tier: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApplyTierIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApplyTierOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    put_threshold: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ThresholdIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThresholdOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_decisions: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/x-ndjson": string;
                };
            };
        };
    };
    get_page_png: {
        parameters: {
            query?: {
                dpi?: number;
            };
            header?: never;
            path: {
                slug: string;
                page: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "image/png": unknown;
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_page_blocks: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                slug: string;
                page: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PageBlock"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_source: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                slug: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    start_export: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RequestIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Not Implemented */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    export_override: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OverrideIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description Not Implemented */
            501: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    export_status: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportStatus"];
                };
            };
        };
    };
    attach_figure: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                fid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AttachIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttachOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_bbox: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                fid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BboxIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BboxOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    detach_figure: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                fid: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AttachIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttachOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_figure_image: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                fid: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_flags: {
        parameters: {
            query?: {
                status?: components["schemas"]["FlagStatus"] | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Flag"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resolve_flag: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                flag_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResolveFlagIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Flag"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_jobs: {
        parameters: {
            query?: {
                status?: string[] | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobInfo"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_job: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RunPlanIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_job: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_job: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_job_log: {
        parameters: {
            query?: {
                after?: number;
                limit?: number;
            };
            header?: never;
            path: {
                job_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    }[];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_learning: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LearningState"];
                };
            };
        };
    };
    put_learning: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LearningFlagsIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LearningState"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    activate_snapshot: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RequestIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LearningState"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    disable_item: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                item_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RequestIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    publish_snapshot: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RequestIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reset_learning: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RequestIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LearningState"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    rollback_snapshot: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                snapshot_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RequestIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LearningState"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_snapshots: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotInfo"][];
                };
            };
        };
    };
    create_snapshot: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RequestIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_probe: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProbeOut"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    run_probe: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProbeOut"];
                };
            };
        };
    };
    get_project: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectInfo"];
                };
            };
        };
    };
    get_blocks: {
        parameters: {
            query?: {
                doc?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScopeBlocks"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    post_confirm: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ConfirmIn"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_groups: {
        parameters: {
            query?: {
                doc?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DocGroups"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_models: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScopeModels"];
                };
            };
        };
    };
    post_regroup: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegroupIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RegroupOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_selection: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SelectionOut"];
                };
            };
        };
    };
    put_selection: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SelectionOp"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SelectionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_summary: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScopeSummary"];
                };
            };
        };
    };
    list_sources: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourceInfo"][];
                };
            };
        };
    };
    upload_sources: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_sources"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JobInfo"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_status: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectStatus"];
                };
            };
        };
    };
    post_action: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewActionIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewActionOut"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EditConflictBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    get_block: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                block_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BlockDetail"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ApiErrorBody"];
                };
            };
        };
    };
    get_cursor: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Cursor"];
                };
            };
        };
    };
    put_cursor: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CursorIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Cursor"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_queue: {
        parameters: {
            query?: {
                sort?: components["schemas"]["QueueSort"] | null;
                view_threshold?: number | null;
                doc?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QueuePage"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
