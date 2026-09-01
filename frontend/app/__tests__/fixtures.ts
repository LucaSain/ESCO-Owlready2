export const skillsFixture = [
  { id: "s1", label: "Python programming" },
  { id: "s2", label: "Data analysis" },
  { id: "s3", label: "Statistical methods" },
];

/** A realistic /match response: three shortlisted occupations, two of which
 *  the reasoner actually classified into (`inferred: true`, and therefore
 *  present in `occupations`), one merely considered. */
export const matchFixture = {
  occupations: ["Data scientist", "Data analyst"],
  shortlist: [
    {
      id: "o1",
      label: "Data scientist",
      shared_skills: 3,
      inferred: true,
      matched_skills: ["s1", "s2", "s3"],
    },
    {
      id: "o2",
      label: "Data analyst",
      shared_skills: 2,
      inferred: true,
      matched_skills: ["s1", "s2"],
    },
    {
      id: "o3",
      label: "Business analyst",
      shared_skills: 1,
      inferred: false,
      matched_skills: ["s2"],
    },
  ],
  skills: skillsFixture,
  skills_used: 3,
  unknown_skill_ids: [],
  skills_not_required: [],
  min_skills: 2,
  seconds: 2.3,
};
