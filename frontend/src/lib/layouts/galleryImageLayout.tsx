import { ImagePlus, Loader2, Trash2 } from "lucide-react";
import {
  createContext,
  type ReactNode,
  type RefObject,
  useCallback,
  useContext,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  type GalleryImageRead,
  type GalleryImageUpdate,
  type GalleryImageVersionRead,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { LazyImage } from "@/components/shared/LazyImage";
import { UserName } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ImagePicker } from "@/components/ui/image-picker";
import { RelativeTime } from "@/components/ui/relative-time";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { type ItemFieldSave, useItemFieldSave } from "@/hooks/useFieldSave";
import {
  galleryImageSaves,
  useDeleteGalleryImageVersion,
  useGalleryImageVersions,
  useUploadGalleryImageVersion,
} from "@/hooks/useGalleries";
import { formatBytes } from "@/lib/fileUtils";
import { ACCEPT_ATTRIBUTE, imageLabel, imageSrc, refuseFile } from "@/lib/galleries";
import { toast } from "@/lib/mascotToast";
import { referenceRef } from "@/lib/smartChips";
import { resolveUploadUrl } from "@/lib/uploadUrl";

import { DetailLayoutView } from "./DetailLayoutView";
import { PlacedProperties, type StoredRegions } from "./detailLayout";
import {
  DescriptionField,
  PlacedPropertyField,
  PropertiesField,
  TagsField,
  TitleField,
} from "./fieldEditors";
import { type FieldDef, PROPERTY_FIELD_PREFIX, useProjectLayoutEnv } from "./fields";
import { GALLERY_IMAGE_FIELDS, GALLERY_IMAGE_LAYOUT, galleryImageFields } from "./galleryImages";
import { PluginFieldOnDetail } from "./plugins";
import { LAYOUT_PARTS, type LayoutContext, type Parts } from "./tree";

/** What a picture's detail shares with its parts, beside the picture itself. */
export interface GalleryImageLayoutContext {
  /** The server says the reader cannot change the picture. */
  readOnly: boolean;
  galleryId: number;
  /** The gallery's initiative; a community's own gallery has none, and so no
   *  properties or links. */
  initiativeId: number | null;
  /** Whether the reader may delete one of its versions. */
  canDeleteVersions: boolean;
  /** Set when the detail is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
  /** Reporting it, and the menu of what else can be done with it. */
  actions: ReactNode;
  /** Drawn in the layout editor, where nothing is changed. */
  preview?: boolean;
}

const DetailContext = createContext<GalleryImageLayoutContext | null>(null);

const useGalleryImageLayout = (): GalleryImageLayoutContext => {
  const context = useContext(DetailContext);
  if (!context) throw new Error("A picture detail part is drawn outside its detail");
  return context;
};

type EditorProps = { image: GalleryImageRead; label: string };
type Save = ItemFieldSave<GalleryImageRead, GalleryImageUpdate>;

/** A field's save, for the gallery the picture is in. */
const useSave = (image: GalleryImageRead, label: string): Save =>
  useItemFieldSave(galleryImageSaves(useGalleryImageLayout().galleryId), image.id, label);

const TitleEditor = ({ image, label }: EditorProps) => {
  const { t } = useTranslation("galleries");
  return (
    <TitleField
      id="gallery-image-title"
      label={label}
      value={image.title ?? ""}
      save={useSave(image, label)}
      readOnly={useGalleryImageLayout().readOnly}
      placeholder={image.original_filename || t("sheet.titlePlaceholder")}
      optional
    />
  );
};

/** The longest caption, as the server allows. */
const CAPTION_LENGTH = 2000;

/** What is said about it, written and saved as a task's description is. */
const CaptionEditor = ({ image, label }: EditorProps) => {
  const { t } = useTranslation("galleries");
  const context = useGalleryImageLayout();
  return (
    <DescriptionField
      field="caption"
      kind={galleryImageSaves(context.galleryId)}
      id={image.id}
      options={{}}
      label={label}
      htmlId="gallery-image-caption"
      value={image.caption ?? null}
      readOnly={context.readOnly}
      initiativeId={context.initiativeId}
      subject={referenceRef(SearchEntityType.gallery_image, image.id)}
      leaving={context.leaving}
      preview={context.preview}
      placeholder={t("sheet.captionPlaceholder")}
      maxLength={CAPTION_LENGTH}
    />
  );
};

const TagsEditor = ({ image, label }: EditorProps) => {
  const { t } = useTranslation("galleries");
  return (
    <TagsField
      label={label}
      tags={image.tags}
      save={useSave(image, label)}
      readOnly={useGalleryImageLayout().readOnly}
      placeholder={t("sheet.tags")}
    />
  );
};

/** Each field's editor on the picture's detail, by its id. */
const FIELD_EDITORS: Record<keyof typeof GALLERY_IMAGE_FIELDS, (props: EditorProps) => ReactNode> =
  {
    title: TitleEditor,
    caption: CaptionEditor,
    tags: TagsEditor,
  };

const propsOf = (image: GalleryImageRead, context: GalleryImageLayoutContext) => ({
  kind: galleryImageSaves(context.galleryId),
  id: image.id,
  properties: image.properties,
  readOnly: context.readOnly,
  initiativeId: context.initiativeId,
  canOpen: { tool: Tool.gallery, id: context.galleryId },
});

/** One field of the picture, by its id: its own, a property or a plug-in's. */
const GalleryImageField = ({
  id,
  image,
  view,
}: {
  id: string;
  image: GalleryImageRead;
  view: LayoutContext;
}) => {
  const { t } = useTranslation(["galleries", "common"]);
  const context = useGalleryImageLayout();
  if (id.startsWith(PROPERTY_FIELD_PREFIX)) {
    return (
      <PlacedPropertyField
        {...propsOf(image, context)}
        propertyId={Number(id.slice(PROPERTY_FIELD_PREFIX.length))}
      />
    );
  }
  const field = view.fields.get(id);
  if (field?.source === "plugin") return <PluginFieldOnDetail field={field} item={image} />;
  if (!Object.hasOwn(FIELD_EDITORS, id)) return null;
  const Editor = FIELD_EDITORS[id as keyof typeof FIELD_EDITORS];
  return (
    <Editor image={image} label={t(GALLERY_IMAGE_FIELDS[id as keyof typeof FIELD_EDITORS].label)} />
  );
};

/** Its properties, but for those the layout places on their own. A
 *  community's own gallery has no definitions to offer. */
const Properties = ({ image }: { image: GalleryImageRead }) => {
  const context = useGalleryImageLayout();
  const placed = useContext(PlacedProperties);
  if (context.initiativeId === null) return null;
  return <PropertiesField {...propsOf(image, context)} except={placed} />;
};

const Relations = ({ image }: { image: GalleryImageRead }) => {
  const { galleryId, initiativeId, readOnly } = useGalleryImageLayout();
  return (
    <ToolRelationsPanel
      tool={Tool.gallery}
      entity={{ id: galleryId, initiative_id: initiativeId }}
      target={{ type: SearchEntityType.gallery_image, id: image.id }}
      canEdit={!readOnly}
      entityTitle={image.title ?? undefined}
    />
  );
};

/** The picture itself. */
const Picture = ({ image }: { image: GalleryImageRead }) => (
  <LazyImage
    src={imageSrc(image)}
    alt={imageLabel(image)}
    aspectRatio={image.width && image.height ? image.width / image.height : 4 / 3}
    className="w-full rounded-lg"
    imgClassName="object-contain"
  />
);

/** Where it came from: who added it and when, and the file. */
const About = ({ image }: { image: GalleryImageRead }) => {
  const { t } = useTranslation("galleries");
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
      <dt className="text-muted-foreground">{t("sheet.uploadedBy")}</dt>
      <dd className="flex min-w-0 items-center gap-2">
        {image.uploader ? (
          <>
            <ProfileAvatar
              user={image.uploader}
              decorations={image.uploader.profile_decorations}
              presence={image.uploader.presence}
              className="size-5 shrink-0"
            />
            <UserName user={image.uploader} nameClassName="min-w-0 truncate" />
          </>
        ) : (
          "—"
        )}
      </dd>
      <dt className="text-muted-foreground">{t("sheet.added")}</dt>
      <dd>
        <RelativeTime date={image.created_at} />
      </dd>
      {image.width && image.height ? (
        <>
          <dt className="text-muted-foreground">{t("sheet.dimensions")}</dt>
          <dd className="tabular-nums">
            {image.width} × {image.height}
          </dd>
        </>
      ) : null}
      {image.file_size ? (
        <>
          <dt className="text-muted-foreground">{t("sheet.size")}</dt>
          <dd>{formatBytes(image.file_size)}</dd>
        </>
      ) : null}
      {image.original_filename ? (
        <>
          <dt className="text-muted-foreground">{t("sheet.filename")}</dt>
          <dd className="truncate">{image.original_filename}</dd>
        </>
      ) : null}
    </dl>
  );
};

/** Its history: where a design round is replaced rather than added to, the
 *  earlier rounds are the story of how it got there. */
const Versions = ({ image }: { image: GalleryImageRead }) => {
  const { t } = useTranslation(["galleries", "common"]);
  const { galleryId, readOnly, canDeleteVersions, preview } = useGalleryImageLayout();
  const versions = useGalleryImageVersions(galleryId, image.id).data ?? [];
  const upload = useUploadGalleryImageVersion(galleryId, {
    onSuccess: () => toast.success(t("sheet.versionUploaded")),
  });
  const [pendingDelete, setPendingDelete] = useState<GalleryImageVersionRead | null>(null);
  const remove = useDeleteGalleryImageVersion(galleryId, {
    onSuccess: () => {
      setPendingDelete(null);
      toast.success(t("sheet.versionDeleted"));
    },
  });
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-medium text-sm">{t("sheet.versions")}</h3>
        {readOnly || preview ? null : (
          <ImagePicker
            variant="button"
            buttonSize="sm"
            accept={ACCEPT_ATTRIBUTE}
            disabled={upload.isPending}
            onSelect={(file) => {
              if (refuseFile(file)) {
                toast.error(t("upload.refusedType"));
                return;
              }
              upload.mutate({ imageId: image.id, file });
            }}
          >
            {upload.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ImagePlus className="size-4" />
            )}
            {t("sheet.uploadVersion")}
          </ImagePicker>
        )}
      </div>
      <ul className="divide-y rounded-md border">
        {versions.map((version) => (
          <li key={version.id} className="flex items-center gap-3 p-2 text-sm">
            <LazyImage
              src={resolveUploadUrl(version.thumbnail_url ?? version.file_url)}
              alt=""
              className="size-12 shrink-0 rounded"
            />
            <div className="min-w-0 flex-1">
              <p className="truncate">
                {t("sheet.versionLabel", { number: version.version_number })}
                {version.is_current && (
                  <span className="ml-2 text-muted-foreground text-xs">{t("sheet.current")}</span>
                )}
              </p>
              <p className="text-muted-foreground text-xs">
                <RelativeTime date={version.created_at} />
                {version.file_size ? ` · ${formatBytes(version.file_size)}` : ""}
              </p>
            </div>
            {canDeleteVersions && versions.length > 1 && !preview && (
              <Button
                variant="ghost"
                size="icon"
                className="size-8 text-muted-foreground hover:text-destructive"
                aria-label={t("sheet.deleteVersion")}
                onClick={() => setPendingDelete(version)}
              >
                <Trash2 className="size-4" />
              </Button>
            )}
          </li>
        ))}
      </ul>
      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(next) => !next && setPendingDelete(null)}
        title={t("sheet.deleteVersionTitle")}
        description={t("sheet.deleteVersionDescription", {
          number: pendingDelete?.version_number ?? 0,
        })}
        confirmLabel={t("common:delete")}
        cancelLabel={t("common:cancel")}
        isLoading={remove.isPending}
        destructive
        onConfirm={() => {
          if (pendingDelete) remove.mutate({ imageId: image.id, versionId: pendingDelete.id });
        }}
      />
    </section>
  );
};

const Actions = () => <>{useGalleryImageLayout().actions}</>;

/** The parts a picture's detail is drawn from. */
const GALLERY_IMAGE_PARTS: Parts<GalleryImageRead> = {
  ...LAYOUT_PARTS,
  field: (node, image, view) => (
    <GalleryImageField id={String(node.props?.field)} image={image} view={view} />
  ),
  properties: (_node, image) => <Properties image={image} />,
  relations: (_node, image) => <Relations image={image} />,
  picture: (_node, image) => <Picture image={image} />,
  about: (_node, image) => <About image={image} />,
  versions: (_node, image) => <Versions image={image} />,
  actions: () => <Actions />,
};

const GALLERY_IMAGE_DETAIL_FIELDS = (plugins: FieldDef[]) => galleryImageFields([], plugins);

// A picture's detail draws no task, so nothing asks it for a task's address.
const NO_TASK = () => "";

/** A picture's detail, drawn from its gallery's layout, or as shipped. */
export const GalleryImageLayoutView = ({
  image,
  context,
  layout,
  editing,
}: {
  image: GalleryImageRead;
  context: GalleryImageLayoutContext;
  layout?: StoredRegions | null;
  /** The layout is being edited: each part is marked with its path. */
  editing?: boolean;
}) => {
  const communityId = useActiveCommunityId();
  const env = useProjectLayoutEnv(useCallback(NO_TASK, []));
  return (
    // Another picture's detail starts afresh, with none of this one's drafts.
    <DetailContext.Provider key={`${communityId}:${image.id}`} value={context}>
      <DetailLayoutView
        spec={GALLERY_IMAGE_LAYOUT}
        item={image}
        initiativeId={context.initiativeId}
        layout={layout}
        editing={editing}
        fields={GALLERY_IMAGE_DETAIL_FIELDS}
        env={env}
        parts={GALLERY_IMAGE_PARTS}
      />
    </DetailContext.Provider>
  );
};
