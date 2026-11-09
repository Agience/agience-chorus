// components/main/MainFooter.tsx
// The platform release this build is for and the agience-chorus commit it was built from, each a
// link to where GitHub shows it: the release's tag on agience-chorus (`platform/<id>`, made by
// `platform_release record`) and the commit. A build that is not a platform release says `dev`.
const REPO = 'https://github.com/Agience/agience-chorus'

export function FooterLabel({ release, sha }: { release: string; sha: string }) {
  const link = 'hover:underline'
  return (
    <span className="cursor-default">
      {release
        ? <a className={link} href={`${REPO}/releases/tag/platform/${release}`} target="_blank" rel="noreferrer">{release}</a>
        : 'dev'}
      {sha && (
        <>
          {' · '}
          <a className={link} href={`${REPO}/commit/${sha}`} target="_blank" rel="noreferrer">{sha}</a>
        </>
      )}
    </span>
  )
}

export default function FooterBar() {
  return (
    <div className="p-2 text-right border-t bg-white text-sm text-gray-600" title={__APP_BUILD_TIME__ || undefined}>
      <FooterLabel release={__APP_VERSION__} sha={__APP_GIT_SHA__} />
    </div>
  )
}
