interface Props {
  speaking: boolean
  name: string
  art?: string
}

export default function CharacterStage({ speaking, name, art }: Props) {
  return (
    <div className={`character-stage ${speaking ? 'speaking' : ''}`}>
      <div className="character">
        {art ? (
          <img className="character-img" src={art} alt={name} />
        ) : (
          <>
            <div className="head">
              <div className="eyes">
                <span className="eye" />
                <span className="eye" />
              </div>
              <div className="mouth" />
            </div>
            <div className="body" />
          </>
        )}
        <span className="character-shadow" aria-hidden="true" />
      </div>
    </div>
  )
}
