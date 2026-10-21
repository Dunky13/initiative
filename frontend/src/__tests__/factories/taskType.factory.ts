import type { TaskTypeRead } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildTaskType(overrides: Partial<TaskTypeRead> = {}): TaskTypeRead {
  counter++;
  return {
    id: counter,
    project_id: 1,
    name: `Type ${counter}`,
    position: counter - 1,
    is_default: false,
    color: "#64748B",
    icon: "square-check",
    layout_preset: "plain",
    ...overrides,
  };
}

/**
 * The four types every new project starts with — Task (the default), Bug, Idea
 * and Milestone — as the server seeds them in English.
 */
export function buildDefaultTaskTypes(projectId: number = 1): TaskTypeRead[] {
  const seeds: Array<Pick<TaskTypeRead, "name" | "icon" | "color" | "layout_preset">> = [
    { name: "Task", icon: "square-check", color: "#64748B", layout_preset: "plain" },
    { name: "Bug", icon: "bug", color: "#EF4444", layout_preset: "fix" },
    { name: "Idea", icon: "lightbulb", color: "#F59E0B", layout_preset: "discussion" },
    { name: "Milestone", icon: "flag", color: "#8B5CF6", layout_preset: "dates" },
  ];
  return seeds.map((seed, index) =>
    buildTaskType({ ...seed, project_id: projectId, position: index, is_default: index === 0 })
  );
}
