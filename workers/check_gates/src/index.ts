import { Worker } from "@notionhq/workers";
import { j } from "@notionhq/workers/schema-builder";
import type { JSONValue } from "@notionhq/workers/types";

const LAB_CONTROL_DB_ID = "3efb3ef6-4c7a-4dc1-a7c5-74982bfe5bcc";
const DEFAULT_MAX_CASCADE_DEPTH = 5;

const worker = new Worker();
export default worker;

type LabControlRow = { flag: boolean; value: number | null };

async function queryLabControl(
	notion: any,
	parameter: string,
): Promise<LabControlRow | null> {
	const res = await notion.databases.query({
		database_id: LAB_CONTROL_DB_ID,
		filter: { property: "Parameter", title: { equals: parameter } },
		page_size: 1,
	});
	const page = res.results?.[0];
	if (!page) return null;
	const props = page.properties ?? {};
	return {
		flag: Boolean(props.Flag?.checkbox),
		value: typeof props.Value?.number === "number" ? props.Value.number : null,
	};
}

worker.tool("checkGates", {
	title: "Check Lab Dispatch Gates",
	description:
		"Check Pre-Flight Mode and Cascade Depth gates before performing Lab " +
		"writes. Returns {proceed, cascade_depth} or {halt, reason, detail}.",
	schema: j.object({
		work_item_id: j
			.string()
			.describe(
				"UUID of the Work Item page. Pass an empty string to skip the Cascade Depth check.",
			),
	}),
	execute: async ({ work_item_id }, { notion }): Promise<JSONValue> => {
		const pf = await queryLabControl(notion, "Pre-Flight Mode");
		if (pf?.flag) {
			return {
				halt: true,
				reason: "pre_flight_active",
				detail: "Pre-Flight Mode is active. All dispatch suspended.",
			};
		}

		let depth = 1;
		if (work_item_id) {
			const page = await notion.pages.retrieve({ page_id: work_item_id });
			const props = (page as any).properties ?? {};
			const raw = props["Cascade Depth"]?.number;
			if (typeof raw === "number") depth = Math.trunc(raw);

			const maxRow = await queryLabControl(notion, "Max Cascade Depth");
			const maxDepth =
				maxRow?.value != null
					? Math.trunc(maxRow.value)
					: DEFAULT_MAX_CASCADE_DEPTH;

			if (depth >= maxDepth) {
				return {
					halt: true,
					reason: "cascade_depth_exceeded",
					detail: `Cascade depth ${depth} >= limit ${maxDepth}.`,
				};
			}
		}

		return { proceed: true, cascade_depth: depth };
	},
});
