import { Fragment } from "react";
import { useTranslation } from "react-i18next";

import type { LegalDocumentRead } from "@/api/generated/initiativeAPI.schemas";
import { legalDocumentHref, useLegalIndex } from "@/hooks/useLegalDocuments";

/** A link to one document, opened beside whatever the reader was doing: in
 *  the app, or where it's kept when that's elsewhere.
 *
 *  A plain anchor rather than a router link: it opens in its own tab, so the
 *  form somebody is halfway through filling in is still there when they come
 *  back, and nothing about reading a policy belongs to the signup route. */
export const DocumentLink = ({
  document,
  children,
}: {
  document: Pick<LegalDocumentRead, "slug" | "url" | "title">;
  children?: React.ReactNode;
}) => (
  <a
    href={legalDocumentHref(document)}
    target="_blank"
    rel="noreferrer"
    className="text-primary underline-offset-4 hover:underline"
  >
    {children ?? document.title}
  </a>
);

/** The documents an account must accept, as links, one after another. */
const RequiredLinks = ({ documents }: { documents: LegalDocumentRead[] }) => (
  <>
    {documents.map((document, index) => (
      <Fragment key={document.slug}>
        {index > 0 ? " · " : null}
        <DocumentLink document={document} />
      </Fragment>
    ))}
  </>
);

/**
 * The line under the Create account button, where there are documents to
 * agree to.
 *
 * Pressing the button is the agreement — there is no box to tick, which is
 * both what every comparable product does and what the terms themselves
 * contemplate. The notice has to sit above the act it describes for that to
 * be true, so it renders immediately before the button rather than in the
 * card footer.
 *
 * Renders nothing where the deployment requires nothing: one with no terms of
 * its own, or one whose terms sit in a contract signed elsewhere.
 */
export const LegalNotice = () => {
  const { t } = useTranslation(["legal", "common"]);
  const { enabled, requiredDocuments } = useLegalIndex();

  if (!enabled || requiredDocuments.length === 0) {
    return null;
  }

  return (
    <p className="text-muted-foreground text-xs">
      {t("legal:signupNotice", { appName: t("common:appName") })}{" "}
      <RequiredLinks documents={requiredDocuments} />
    </p>
  );
};

/** The same links, without the sentence around them. */
export const LegalDocumentLinks = () => {
  const { requiredDocuments } = useLegalIndex();

  return (
    <div className="flex flex-wrap gap-4 text-sm">
      {requiredDocuments.map((document) => (
        <DocumentLink key={document.slug} document={document} />
      ))}
    </div>
  );
};

/** A link to the deployment's privacy policy, where it publishes one. */
export const PrivacyLink = () => {
  const { documents } = useLegalIndex();
  const privacy = documents.find((document) => document.slug === "privacy");
  return privacy ? <DocumentLink document={privacy} /> : null;
};
