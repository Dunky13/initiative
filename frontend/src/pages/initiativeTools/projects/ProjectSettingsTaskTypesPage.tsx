/**
 * `/settings/task-types` — the kinds of task this project holds, and the way
 * into each one's page.
 */

import { useParams } from "@tanstack/react-router";

import { ProjectTaskTypesManager } from "@/components/projects/ProjectTaskTypesManager";
import { useProject } from "@/hooks/useProjects";

export const ProjectSettingsTaskTypesPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId?: string };
  const parsedId = projectId ? Number(projectId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const projectQuery = useProject(isValidId ? parsedId : null);
  const project = projectQuery.data;

  if (!project) return null;

  return (
    <ProjectTaskTypesManager
      projectId={project.id}
      initiativeId={project.initiative_id}
      canManage={project.can.edit}
    />
  );
};
